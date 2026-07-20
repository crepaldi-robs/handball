from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
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


class LoginLimiter:
    def __init__(self, limit: int = 5, window_seconds: int = 15 * 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def allowed(self, key: str) -> bool:
        now = time.monotonic()
        attempts = self._attempts[key]
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()
        return len(attempts) < self.limit

    def fail(self, key: str) -> None:
        self._attempts[key].append(time.monotonic())

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
