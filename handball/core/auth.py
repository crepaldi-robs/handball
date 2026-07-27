from __future__ import annotations

import math
import hashlib
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import AppSettings
from .authorization import AccessContext, Permission


@dataclass(frozen=True)
class AuthSession:
    user_id: int
    person_id: int | None
    session_id: str
    username: str
    display_name: str
    csrf_token: str
    team_ids: frozenset[int]
    system_roles: frozenset[str]
    team_roles: frozenset[str]
    permissions: frozenset[Permission]
    linked_player_id: int | None
    must_change_password: bool = False

    def to_access_context(self) -> AccessContext:
        return AccessContext(
            user_id=self.user_id,
            person_id=self.person_id,
            session_id=self.session_id,
            username=self.username,
            display_name=self.display_name,
            team_ids=self.team_ids,
            system_roles=self.system_roles,
            team_roles=self.team_roles,
            permissions=self.permissions,
            linked_player_id=self.linked_player_id,
            csrf_token=self.csrf_token,
            must_change_password=self.must_change_password,
        )


@dataclass(frozen=True)
class LoginLimitStatus:
    limit: int
    window_seconds: int
    attempts: int
    blocked: bool
    retry_after_seconds: int


class LoginLimiter:
    def __init__(
        self,
        limit: int = 5,
        window_seconds: int = 15 * 60,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("O limite de tentativas deve ser positivo.")
        if window_seconds < 1:
            raise ValueError("A janela de bloqueio deve ser positiva.")
        self.limit = limit
        self.window_seconds = window_seconds
        self._monotonic = monotonic or time.monotonic
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def _status(self, key: str, now: float) -> LoginLimitStatus:
        attempts = self._attempts[key]
        while attempts and now - attempts[0] >= self.window_seconds:
            attempts.popleft()

        blocked = len(attempts) >= self.limit
        retry_after_seconds = 0
        if blocked:
            retry_after_seconds = math.ceil(
                self.window_seconds - (now - attempts[0])
            )
        return LoginLimitStatus(
            limit=self.limit,
            window_seconds=self.window_seconds,
            attempts=len(attempts),
            blocked=blocked,
            retry_after_seconds=retry_after_seconds,
        )

    def status(self, key: str) -> LoginLimitStatus:
        return self._status(key, self._monotonic())

    def allowed(self, key: str) -> bool:
        return not self.status(key).blocked

    def fail(self, key: str) -> LoginLimitStatus:
        now = self._monotonic()
        self._status(key, now)
        self._attempts[key].append(now)
        return self._status(key, now)

    def clear(self, key: str) -> None:
        self._attempts.pop(key, None)


def login_client_key(request: Request, trusted_proxies: frozenset[str]) -> str:
    """Identifica o cliente real do login, sem aceitar cabeçalho forjado.

    Em produção o Cloudflare Tunnel entrega tudo pelo loopback, então
    `request.client.host` é idêntico para o mundo inteiro e o limitador de
    tentativas viraria um balde único global. O cabeçalho de IP original só é
    considerado quando o peer imediato é um proxy declarado como confiável — o
    Cloudflare sobrescreve `CF-Connecting-IP`, então ele não é forjável por quem
    passa pelo túnel. Vindo de qualquer outra origem, vale o endereço observado.
    """

    direct = request.client.host if request.client else ""
    if direct and direct in trusted_proxies:
        forwarded = request.headers.get("cf-connecting-ip", "").strip()
        if not forwarded:
            forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return direct or "unknown"


class AuthManager:
    cookie_name = "handball_session"

    def __init__(self, settings: AppSettings, unit_of_work_factory: Any) -> None:
        self.settings = settings
        self.password_hasher = PasswordHasher()
        self.limiter = LoginLimiter()
        self.unit_of_work_factory = unit_of_work_factory

    def verify_credentials(self, username: str, password: str) -> int | None:
        with self.unit_of_work_factory() as unit_of_work:
            user = unit_of_work.identity.get_user_by_username(username)
            if user is None or not bool(user["active"]):
                return None
            try:
                if self.password_hasher.verify(str(user["password_hash"]), password):
                    unit_of_work.identity.mark_login(int(user["id"]))
                    return int(user["id"])
            except (VerifyMismatchError, InvalidHashError):
                pass
            return None

    def create_token(self, user_id: int, *, user_agent: str = "") -> tuple[str, AuthSession]:
        csrf_token = secrets.token_urlsafe(32)
        with self.unit_of_work_factory() as unit_of_work:
            user = unit_of_work.identity.get_user(user_id)
            if user is None:
                raise ValueError("Conta inexistente.")
            token, session_id = unit_of_work.identity.create_session(
                user_id,
                (datetime.now(UTC) + timedelta(seconds=self.settings.session_max_age_seconds)).isoformat(timespec="seconds"),
                csrf_token,
                user_agent_hash=(
                    hashlib.sha256(user_agent.encode("utf-8")).hexdigest()
                    if user_agent else None
                ),
            )
            data = unit_of_work.identity.access_context_data(token, touch=False)
        if data is None:
            raise ValueError("Sessão não pôde ser materializada.")
        return token, self._session_from_data(data)

    def read_token(
        self,
        token: str | None,
        *,
        touch: bool = True,
    ) -> AuthSession | None:
        if not token:
            return None
        with self.unit_of_work_factory(read_only=not touch) as unit_of_work:
            data = unit_of_work.identity.access_context_data(token, touch=touch)
        return self._session_from_data(data) if data else None

    @staticmethod
    def _session_from_data(data: dict[str, Any]) -> AuthSession:
        return AuthSession(
            user_id=int(data["user_id"]),
            person_id=int(data["person_id"]) if data.get("person_id") is not None else None,
            session_id=str(data["session_id"]),
            username=str(data["username"]),
            display_name=str(data.get("display_name") or data.get("full_name") or data["username"]),
            csrf_token=str(data["csrf_token"]),
            team_ids=frozenset(int(value) for value in data["team_ids"]),
            system_roles=frozenset(str(value) for value in data["system_roles"]),
            team_roles=frozenset(str(value) for value in data["team_roles"]),
            permissions=frozenset(Permission(value) for value in data["permissions"]),
            linked_player_id=(int(data["linked_player_id"]) if data.get("linked_player_id") is not None else None),
            must_change_password=bool(data.get("must_change_password")),
        )


def session_from_request(
    request: Request,
    *,
    touch: bool = True,
) -> AuthSession | None:
    auth: AuthManager = request.app.state.auth
    session = auth.read_token(request.cookies.get(auth.cookie_name), touch=touch)
    if session is not None:
        request.state.access_context = session.to_access_context()
    return session


def require_session(request: Request) -> AuthSession:
    session = session_from_request(request)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return session


def require_write_session(request: Request) -> AuthSession:
    session = require_session(request)
    supplied = request.headers.get("X-CSRF-Token", "")
    if not secrets.compare_digest(supplied, session.csrf_token):
        raise HTTPException(status_code=403, detail="Token CSRF inválido.")
    return session


def _format_duration(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    for value, singular, plural in (
        (hours, "hora", "horas"),
        (minutes, "minuto", "minutos"),
        (seconds, "segundo", "segundos"),
    ):
        if value:
            parts.append(f"{value} {singular if value == 1 else plural}")
    return " e ".join(parts) if parts else "0 segundos"


def _login_limit_message(limit_status: LoginLimitStatus) -> str:
    policy_duration = _format_duration(limit_status.window_seconds)
    remaining_duration = _format_duration(limit_status.retry_after_seconds)
    return (
        f"Limite de {limit_status.limit} tentativas atingido. "
        "A política atual bloqueia novas tentativas por até "
        f"{policy_duration}. Tente novamente em {remaining_duration}."
    )


def create_auth_router(
    settings: AppSettings,
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> Response:
        if session_from_request(request):
            return RedirectResponse("/app", status_code=303)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": None, "username": settings.admin_username},
        )

    @router.post("/login", response_class=HTMLResponse)
    def login(
        request: Request,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
    ) -> Response:
        auth: AuthManager = request.app.state.auth
        client_key = login_client_key(request, settings.trusted_proxies)
        limit_status = auth.limiter.status(client_key)
        if limit_status.blocked:
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": _login_limit_message(limit_status),
                    "username": username,
                },
                status_code=429,
                headers={"Retry-After": str(limit_status.retry_after_seconds)},
            )
        user_id = auth.verify_credentials(username, password)
        if user_id is None:
            limit_status = auth.limiter.fail(client_key)
            if limit_status.blocked:
                return templates.TemplateResponse(
                    request,
                    "login.html",
                    {
                        "error": _login_limit_message(limit_status),
                        "username": username,
                    },
                    status_code=429,
                    headers={"Retry-After": str(limit_status.retry_after_seconds)},
                )
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Usuário ou senha inválidos.", "username": username},
                status_code=401,
            )

        auth.limiter.clear(client_key)
        token, _ = auth.create_token(
            user_id,
            user_agent=request.headers.get("user-agent", "")[:500],
        )
        response = RedirectResponse("/app", status_code=303)
        response.set_cookie(
            auth.cookie_name,
            token,
            max_age=settings.session_max_age_seconds,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        return response

    @router.post("/logout")
    def logout(
        request: Request,
        csrf_token: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        auth: AuthManager = request.app.state.auth
        token = request.cookies.get(auth.cookie_name)
        session = auth.read_token(token)
        if session is not None and not secrets.compare_digest(csrf_token, session.csrf_token):
            raise HTTPException(status_code=403, detail="Token CSRF inválido.")
        if token:
            with auth.unit_of_work_factory() as unit_of_work:
                unit_of_work.identity.revoke_session_token(token)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(auth.cookie_name, path="/")
        return response

    return router
