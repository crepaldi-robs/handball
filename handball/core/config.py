from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


def _as_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


@dataclass(frozen=True)
class AppSettings:
    """Configuração compartilhada que não contém detalhes de persistência."""

    admin_username: str
    password_hash: str
    secret_key: str
    config_path: Path
    cookie_secure: bool = False
    session_max_age_seconds: int = 12 * 60 * 60
    release_id: str = "development"
    maintenance_file: Path | None = None

    @classmethod
    def load(cls, root_dir: Path) -> "AppSettings":
        config_path = Path(
            os.environ.get(
                "ATTENDANCE_CONFIG_PATH",
                root_dir / "data" / "app-config.json",
            )
        )
        data: dict[str, object] = {}
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))

        username = os.environ.get(
            "ATTENDANCE_ADMIN_USERNAME",
            str(data.get("admin_username") or "roberto"),
        ).strip()
        password_hash = os.environ.get(
            "ATTENDANCE_PASSWORD_HASH",
            str(data.get("password_hash") or ""),
        ).strip()
        secret_key = os.environ.get(
            "ATTENDANCE_SECRET_KEY",
            str(data.get("secret_key") or ""),
        ).strip()
        if not username or not password_hash or len(secret_key) < 32:
            raise ConfigurationError(
                "Configuração de autenticação ausente. Execute scripts\\setup.ps1."
            )

        return cls(
            admin_username=username,
            password_hash=password_hash,
            secret_key=secret_key,
            config_path=config_path,
            cookie_secure=_as_bool(
                os.environ.get("ATTENDANCE_COOKIE_SECURE", data.get("cookie_secure")),
                False,
            ),
            session_max_age_seconds=int(
                os.environ.get(
                    "ATTENDANCE_SESSION_MAX_AGE",
                    str(data.get("session_max_age_seconds") or 12 * 60 * 60),
                )
            ),
            release_id=(
                os.environ.get("ATTENDANCE_RELEASE_ID", "development").strip()
                or "development"
            )[:100],
            maintenance_file=(
                Path(os.environ["ATTENDANCE_MAINTENANCE_FILE"])
                if os.environ.get("ATTENDANCE_MAINTENANCE_FILE")
                else None
            ),
        )

    @classmethod
    def from_legacy(cls, settings: Any, root_dir: Path) -> "AppSettings":
        """Converte a configuração antiga sem transportar caminhos de dados."""

        config_path = Path(
            os.environ.get(
                "ATTENDANCE_CONFIG_PATH",
                root_dir / "data" / "app-config.json",
            )
        )
        return cls(
            admin_username=str(settings.admin_username),
            password_hash=str(settings.password_hash),
            secret_key=str(settings.secret_key),
            config_path=config_path,
            cookie_secure=bool(settings.cookie_secure),
            session_max_age_seconds=int(settings.session_max_age_seconds),
            release_id=str(getattr(settings, "release_id", "development")),
            maintenance_file=getattr(settings, "maintenance_file", None),
        )
