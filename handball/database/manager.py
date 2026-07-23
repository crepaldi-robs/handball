from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping
from zoneinfo import ZoneInfo

from .adapters import SQLiteAdapter
from .contracts import BackupDownload, DatabaseCompatibilityError
from .unit_of_work import UnitOfWork, UnitOfWorkFactory


class DatabaseManager:
    """Ponto de composição que concentra caminhos, adaptador e transações."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        backup_dir: str | Path | None = None,
        busy_timeout_ms: int = 30_000,
    ) -> None:
        self._db_path = Path(db_path)
        self._backup_dir = Path(backup_dir) if backup_dir is not None else None
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._adapter = SQLiteAdapter(
            self._db_path,
            busy_timeout_ms=self._busy_timeout_ms,
        )

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def backup_dir(self) -> Path | None:
        return self._backup_dir

    @property
    def busy_timeout_ms(self) -> int:
        return self._busy_timeout_ms

    @classmethod
    def from_config(
        cls,
        config_path: str | Path,
        *,
        expected_database_path: str | Path | None = None,
        busy_timeout_ms: int = 30_000,
    ) -> DatabaseManager:
        path = Path(config_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise DatabaseCompatibilityError(
                f"Configuração de persistência não encontrada: {path}."
            ) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DatabaseCompatibilityError(
                f"Configuração de persistência inválida: {path}."
            ) from exc
        if not isinstance(payload, dict):
            raise DatabaseCompatibilityError(
                f"Configuração de persistência inválida: {path}."
            )

        db_value = payload.get("db_path")
        if not isinstance(db_value, str) or not db_value.strip():
            raise DatabaseCompatibilityError(
                "A configuração não define um caminho de banco válido."
            )
        database_path = Path(db_value.strip())
        if expected_database_path is not None:
            expected = Path(expected_database_path)
            if (
                os.path.normcase(os.path.abspath(database_path))
                != os.path.normcase(os.path.abspath(expected))
            ):
                raise DatabaseCompatibilityError(
                    "O banco configurado não corresponde ao caminho esperado."
                )

        backup_value = payload.get("backup_dir")
        backup_dir = (
            Path(backup_value.strip())
            if isinstance(backup_value, str) and backup_value.strip()
            else None
        )
        return cls(
            database_path,
            backup_dir=backup_dir,
            busy_timeout_ms=busy_timeout_ms,
        )

    @classmethod
    def from_environment(
        cls,
        root_dir: str | Path | None = None,
        *,
        config_path: str | Path | None = None,
        environment: Mapping[str, str] | None = None,
        busy_timeout_ms: int = 30_000,
    ) -> DatabaseManager:
        env = os.environ if environment is None else environment
        root = Path.cwd() if root_dir is None else Path(root_dir)
        configured_path = Path(
            config_path
            or env.get("ATTENDANCE_CONFIG_PATH")
            or root / "data" / "app-config.json"
        )

        data: dict[str, object] = {}
        if configured_path.exists():
            try:
                raw = json.loads(configured_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise DatabaseCompatibilityError(
                    f"Configuração de persistência inválida: {configured_path}."
                ) from exc
            if not isinstance(raw, dict):
                raise DatabaseCompatibilityError(
                    f"Configuração de persistência inválida: {configured_path}."
                )
            data = raw

        db_value = env.get("ATTENDANCE_DB_PATH") or data.get("db_path")
        backup_value = env.get("ATTENDANCE_BACKUP_DIR") or data.get("backup_dir")
        database_path = Path(str(db_value or root / "data" / "presencas.db"))
        backup_dir = Path(str(backup_value or root / "backups"))
        return cls(
            database_path,
            backup_dir=backup_dir,
            busy_timeout_ms=busy_timeout_ms,
        )

    def unit_of_work(self, *, read_only: bool = False) -> UnitOfWork:
        return UnitOfWork(self, read_only=read_only)

    def unit_of_work_factory(self) -> UnitOfWorkFactory:
        return UnitOfWorkFactory(self)

    @contextmanager
    def read_only_connection(self, *, immutable: bool = False) -> Iterator[Any]:
        connection = self._adapter.connect_read_only(immutable=immutable)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def write_connection(self) -> Iterator[Any]:
        with self.unit_of_work() as unit_of_work:
            yield unit_of_work.connection

    def attendance_repository(self):
        from .repositories.attendance import AttendanceRepository

        return AttendanceRepository(self)

    def bootstrap(self, *, legacy_admin: tuple[str, str] | None = None) -> None:
        self.attendance_repository().bootstrap(legacy_admin=legacy_admin)

    def validate_existing(
        self,
        *,
        quick_check: bool = False,
        immutable: bool = False,
    ) -> int:
        return self.attendance_repository().validate_existing(
            quick_check=quick_check,
            immutable=immutable,
        )

    def logical_fingerprint(self) -> str:
        return self.attendance_repository().logical_fingerprint()

    def backup_to(
        self,
        destination: str | Path,
        *,
        pre_migration: bool = False,
        expected_fingerprint: str | None = None,
    ) -> Path:
        return self.attendance_repository().backup_to(
            destination,
            pre_migration=pre_migration,
            expected_fingerprint=expected_fingerprint,
        )

    def create_backup(self, filename: str) -> Path:
        if self._backup_dir is None:
            raise DatabaseCompatibilityError(
                "Diretório de backups não foi configurado."
            )
        requested = Path(filename)
        if (
            requested.is_absolute()
            or requested.name != filename
            or requested.suffix.casefold() != ".db"
            or filename in {"", ".", ".."}
        ):
            raise ValueError("O nome do backup deve ser um arquivo .db simples.")
        return self.backup_to(self._backup_dir / requested.name)

    def create_backup_download(self) -> BackupDownload:
        """Cria nome e conteúdo do download dentro da fronteira de persistência."""

        timestamp = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime(
            "%Y%m%d-%H%M%S-%f"
        )
        backup_path = self.create_backup(f"presencas-{timestamp}.db")
        return BackupDownload(
            filename=backup_path.name,
            media_type="application/vnd.sqlite3",
            content_length=backup_path.stat().st_size,
            _open_binary=lambda: backup_path.open("rb"),
        )
