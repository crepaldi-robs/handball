from __future__ import annotations

import math
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import AppSettings


@dataclass(frozen=True)
class AuthSession:
    username: str
    csrf_token: str


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


class AuthManager:
    cookie_name = "handball_session"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.password_hasher = PasswordHasher()
        self.serializer = URLSafeTimedSerializer(
            settings.secret_key,
            salt="handball-session-v1",
        )
        self.limiter = LoginLimiter()

    def verify_credentials(self, username: str, password: str) -> bool:
        if not secrets.compare_digest(username.strip(), self.settings.admin_username):
            return False
        try:
            return self.password_hasher.verify(self.settings.password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def create_token(self) -> tuple[str, AuthSession]:
        session = AuthSession(
            username=self.settings.admin_username,
            csrf_token=secrets.token_urlsafe(32),
        )
        token = self.serializer.dumps(
            {"sub": session.username, "csrf": session.csrf_token}
        )
        return token, session

    def read_token(self, token: str | None) -> AuthSession | None:
        if not token:
            return None
        try:
            payload: dict[str, Any] = self.serializer.loads(
                token,
                max_age=self.settings.session_max_age_seconds,
            )
        except (BadSignature, SignatureExpired):
            return None
        if payload.get("sub") != self.settings.admin_username:
            return None
        csrf = str(payload.get("csrf") or "")
        if not csrf:
            return None
        return AuthSession(username=self.settings.admin_username, csrf_token=csrf)


def session_from_request(request: Request) -> AuthSession | None:
    auth: AuthManager = request.app.state.auth
    return auth.read_token(request.cookies.get(auth.cookie_name))


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
        client_key = request.client.host if request.client else "unknown"
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
        if not auth.verify_credentials(username, password):
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
        token, _ = auth.create_token()
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
    def logout(request: Request) -> RedirectResponse:
        auth: AuthManager = request.app.state.auth
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(auth.cookie_name, path="/")
        return response

    return router
