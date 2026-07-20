from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


@dataclass(frozen=True)
class AppSettings:
    db_path: Path
    admin_username: str
    password_hash: str
    secret_key: str
    cookie_secure: bool = False
    session_max_age_seconds: int = 12 * 60 * 60
    backup_dir: Path | None = None

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

        db_path = Path(
            os.environ.get(
                "ATTENDANCE_DB_PATH",
                str(data.get("db_path") or root_dir / "data" / "presencas.db"),
            )
        )
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
            raise RuntimeError(
                "Configuração de autenticação ausente. Execute scripts\\setup.ps1."
            )

        backup_dir_value = os.environ.get(
            "ATTENDANCE_BACKUP_DIR",
            str(data.get("backup_dir") or root_dir / "backups"),
        )
        return cls(
            db_path=db_path,
            admin_username=username,
            password_hash=password_hash,
            secret_key=secret_key,
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
            backup_dir=Path(backup_dir_value),
        )
