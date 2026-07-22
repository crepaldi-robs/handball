from __future__ import annotations

import sqlite3
from pathlib import Path

from ..contracts import DatabaseCompatibilityError


class SQLiteAdapter:
    """Único adaptador que conhece como abrir e configurar conexões SQLite."""

    def __init__(self, database_path: str | Path, *, busy_timeout_ms: int = 30_000):
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms não pode ser negativo.")
        self.database_path = Path(database_path)
        self.busy_timeout_ms = int(busy_timeout_ms)

    def connect_read_only(self, *, immutable: bool = False) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise DatabaseCompatibilityError(
                f"Banco persistente não encontrado: {self.database_path}. "
                "A inicialização foi cancelada para evitar criar uma base vazia."
            )

        immutable_parameter = "&immutable=1" if immutable else ""
        database_uri = (
            f"{self.database_path.resolve().as_uri()}?mode=ro{immutable_parameter}"
        )
        try:
            connection = sqlite3.connect(
                database_uri,
                uri=True,
                timeout=self.busy_timeout_ms / 1000,
                isolation_level=None,
                cached_statements=0,
            )
        except sqlite3.Error as exc:
            raise DatabaseCompatibilityError(
                f"Não foi possível abrir o banco persistente: {self.database_path}."
            ) from exc

        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON").close()
            connection.execute(
                f"PRAGMA busy_timeout = {self.busy_timeout_ms}"
            ).close()
            connection.execute("PRAGMA query_only = ON").close()
        except Exception:
            connection.close()
            raise
        return connection
    def connect_write(self) -> sqlite3.Connection:
        """Abre somente banco existente; nunca cria arquivo implicitamente."""

        if not self.database_path.is_file():
            raise DatabaseCompatibilityError(
                f"Banco persistente não encontrado: {self.database_path}. "
                "Use o bootstrap explícito da primeira instalação."
            )
        database_uri = f"{self.database_path.resolve().as_uri()}?mode=rw"
        try:
            connection = sqlite3.connect(
                database_uri,
                uri=True,
                timeout=self.busy_timeout_ms / 1000,
                isolation_level=None,
                cached_statements=0,
            )
        except sqlite3.Error as exc:
            raise DatabaseCompatibilityError(
                f"Não foi possível abrir o banco persistente: {self.database_path}."
            ) from exc

        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON").close()
            connection.execute(
                f"PRAGMA busy_timeout = {self.busy_timeout_ms}"
            ).close()
        except Exception:
            connection.close()
            raise
        return connection
