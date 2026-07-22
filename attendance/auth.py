from __future__ import annotations

import math
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
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
