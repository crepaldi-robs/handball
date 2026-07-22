from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator
from uuid import uuid4
from zoneinfo import ZoneInfo

from .migrations import (
    LATEST_SCHEMA_VERSION,
    DatabaseMigrator,
    logical_fingerprint as migration_logical_fingerprint,
)
from .models import CONFIRMATION_LABELS, INITIAL_MEMBERS

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
SCHEMA_VERSION = LATEST_SCHEMA_VERSION

REQUIRED_SCHEMA: dict[str, frozenset[str]] = {
    "team_members": frozenset(
        {"id", "name", "position", "active", "created_at", "updated_at"}
    ),
    "training_sessions": frozenset(
        {
            "id",
            "training_date",
            "notes",
            "is_finalized",
            "created_at",
            "updated_at",
        }
    ),
    "attendance_records": frozenset(
        {
            "id",
            "session_id",
            "member_id",
            "confirmation_status",
            "present",
            "notes",
            "version",
            "updated_at",
        }
    ),
    "attendance_audit_log": frozenset(
        {
            "id",
            "session_id",
            "member_id",
            "old_confirmation_status",
            "new_confirmation_status",
            "old_present",
            "new_present",
            "old_notes",
            "new_notes",
            "changed_at",
            "source",
        }
    ),
    "sync_operations": frozenset(
        {"operation_id", "request_hash", "response_json", "created_at"}
    ),
}


class DatabaseCompatibilityError(RuntimeError):
    """O banco persistente está ausente, corrompido ou incompatível."""


def _now_iso() -> str:
    return datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")


def _date_iso(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value).isoformat()


def _fetchall(
    conn: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...] = (),
) -> list[sqlite3.Row]:
    cursor = conn.execute(sql, parameters)
    try:
        return cursor.fetchall()
    finally:
        cursor.close()


def _fetchone(
    conn: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...] = (),
) -> sqlite3.Row | None:
    cursor = conn.execute(sql, parameters)
    try:
        return cursor.fetchone()
    finally:
        cursor.close()


class AttendanceRepository:
    """Camada de persistência SQLite do registrador de presenças."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Abre uma conexão de leitura e escrita para operações de domínio.

        Este método não deve ser usado para verificar se um banco de produção
        existe: o SQLite criaria um arquivo vazio. Startup, backup e update usam
        ``read_only_connection`` e falham se o arquivo persistente estiver ausente.
        """

        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON").close()
        conn.execute("PRAGMA busy_timeout = 30000").close()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            conn = None

    @contextmanager
    def read_only_connection(
        self,
        *,
        immutable: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        """Abre o SQLite existente sem possibilidade de criar ou gravar nele."""

        if not self.db_path.is_file():
            raise DatabaseCompatibilityError(
                f"Banco persistente não encontrado: {self.db_path}. "
                "A inicialização foi cancelada para evitar criar uma base vazia."
            )

        immutable_parameter = "&immutable=1" if immutable else ""
        database_uri = (
            f"{self.db_path.resolve().as_uri()}?mode=ro{immutable_parameter}"
        )
        try:
            conn = sqlite3.connect(
                database_uri,
                uri=True,
                timeout=30,
                cached_statements=0,
            )
        except sqlite3.Error as exc:
            raise DatabaseCompatibilityError(
                f"Não foi possível abrir o banco persistente: {self.db_path}."
            ) from exc

        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON").close()
        conn.execute("PRAGMA busy_timeout = 30000").close()
        conn.execute("PRAGMA query_only = ON").close()
        try:
            yield conn
        finally:
            conn.close()
            conn = None

    def bootstrap(self) -> None:
        """Cria a base somente no bootstrap; banco existente é apenas validado.

        Atualizações e o startup web não chamam este método. Ele é a operação
        explícita de primeira instalação e também serve aos testes isolados.
        """

        if self.db_path.exists():
            self.validate_existing()
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        candidate = self.db_path.with_name(
            f".{self.db_path.name}.{uuid4().hex}.bootstrap.partial"
        )
        candidate_repository = AttendanceRepository(candidate)
        try:
            DatabaseMigrator(candidate).bootstrap_new(
                app_version="1.0.0",
                origin="initial-bootstrap",
            )
            candidate_repository.seed_initial_members()
            candidate_repository.validate_existing(quick_check=True)

            # O hard link publica o arquivo de forma atômica e sem sobrescrever
            # um banco que outra instalação possa ter criado durante o preparo.
            try:
                os.link(candidate, self.db_path)
            except FileExistsError:
                self.validate_existing(quick_check=True)
            else:
                candidate.unlink()
                self.validate_existing(quick_check=True)
        finally:
            for artifact in (
                candidate,
                Path(str(candidate) + "-journal"),
                Path(str(candidate) + "-wal"),
                Path(str(candidate) + "-shm"),
            ):
                artifact.unlink(missing_ok=True)

    def validate_existing(
        self,
        *,
        quick_check: bool = False,
        immutable: bool = False,
    ) -> int:
        """Valida compatibilidade sem DDL, seed, migration ou criação de arquivo."""

        with self.read_only_connection(immutable=immutable) as conn:
            existing_tables = {
                str(row["name"])
                for row in _fetchall(
                    conn,
                    "SELECT name FROM sqlite_schema WHERE type = 'table'"
                )
            }
            missing_tables = sorted(set(REQUIRED_SCHEMA) - existing_tables)
            if missing_tables:
                raise DatabaseCompatibilityError(
                    "Esquema incompatível; tabelas ausentes: "
                    + ", ".join(missing_tables)
                    + ". Nenhuma migration foi executada automaticamente."
                )

            for table_name, required_columns in REQUIRED_SCHEMA.items():
                columns = {
                    str(row["name"])
                    for row in _fetchall(
                        conn,
                        f'PRAGMA table_info("{table_name}")',
                    )
                }
                missing_columns = sorted(required_columns - columns)
                if missing_columns:
                    raise DatabaseCompatibilityError(
                        f"Esquema incompatível em {table_name}; colunas ausentes: "
                        + ", ".join(missing_columns)
                        + ". Nenhuma migration foi executada automaticamente."
                    )

            _fetchone(conn, "SELECT 1")
            if quick_check:
                self._require_quick_check_ok(conn)
                violations = _fetchall(conn, "PRAGMA foreign_key_check")
                if violations:
                    raise DatabaseCompatibilityError(
                        "PRAGMA foreign_key_check encontrou vínculos inválidos."
                    )

        migration_status = DatabaseMigrator(self.db_path).status()
        if not migration_status.compatible:
            detail = " ".join(migration_status.problems)
            raise DatabaseCompatibilityError(
                "Versão formal do esquema incompatível com esta aplicação."
                + (f" {detail}" if detail else "")
            )
        return migration_status.current_version

    @staticmethod
    def _require_quick_check_ok(conn: sqlite3.Connection) -> None:
        results = [str(row[0]) for row in _fetchall(conn, "PRAGMA quick_check")]
        if results != ["ok"]:
            detail = "; ".join(results) or "sem resultado"
            raise DatabaseCompatibilityError(
                f"PRAGMA quick_check reprovou o banco: {detail}"
            )

    def quick_check(self) -> str:
        """Exige o resultado literal ``ok`` da verificação de integridade."""

        with self.read_only_connection() as conn:
            self._require_quick_check_ok(conn)
        return "ok"

    def _validate_physical_integrity(self, *, immutable: bool = False) -> None:
        """Valida integridade física sem exigir o esquema da versão atual."""

        with self.read_only_connection(immutable=immutable) as conn:
            self._require_quick_check_ok(conn)
            violations = _fetchall(conn, "PRAGMA foreign_key_check")
            if violations:
                raise DatabaseCompatibilityError(
                    "PRAGMA foreign_key_check encontrou vínculos inválidos."
                )

    def logical_fingerprint(self) -> str:
        """Resume esquema e conteúdo lógico sem expor os dados operacionais."""

        self.validate_existing()
        return migration_logical_fingerprint(self.db_path)

    def seed_initial_members(self) -> None:
        """Semeia apenas o bootstrap sem sobrescrever decisões do usuário."""

        now = _now_iso()
        with self.connection() as conn:
            for name, position in INITIAL_MEMBERS:
                conn.execute(
                    """
                    INSERT INTO team_members(name, position, active, created_at, updated_at)
                    VALUES (?, ?, 1, ?, ?)
                    ON CONFLICT(name) DO NOTHING
                    """,
                    (name, position, now, now),
                )

    def get_or_create_session(self, training_date: date | str) -> dict[str, Any]:
        training_date_iso = _date_iso(training_date)
        now = _now_iso()

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO training_sessions(
                    training_date, notes, is_finalized, created_at, updated_at
                )
                VALUES (?, '', 0, ?, ?)
                ON CONFLICT(training_date) DO NOTHING
                """,
                (training_date_iso, now, now),
            )
            row = conn.execute(
                "SELECT * FROM training_sessions WHERE training_date = ?",
                (training_date_iso,),
            ).fetchone()

        if row is None:
            raise RuntimeError("Não foi possível criar ou carregar o treino.")

        session = dict(row)
        self.ensure_attendance_records(int(session["id"]))
        return session

    def ensure_attendance_records(self, session_id: int) -> None:
        now = _now_iso()
        with self.connection() as conn:
            active_members = conn.execute(
                "SELECT id FROM team_members WHERE active = 1 ORDER BY name"
            ).fetchall()
            for member in active_members:
                conn.execute(
                    """
                    INSERT INTO attendance_records(
                        session_id, member_id, confirmation_status,
                        present, notes, updated_at
                    )
                    VALUES (?, ?, 'PENDING', NULL, '', ?)
                    ON CONFLICT(session_id, member_id) DO NOTHING
                    """,
                    (session_id, int(member["id"]), now),
                )

    def get_session(self, session_id: int) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM training_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Treino {session_id} não encontrado.")
        return dict(row)

    def get_session_records(self, session_id: int) -> list[dict[str, Any]]:
        self.ensure_attendance_records(session_id)
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    ar.id AS record_id,
                    ar.session_id,
                    tm.id AS member_id,
                    tm.name,
                    tm.position,
                    ar.confirmation_status,
                    ar.present,
                    ar.notes,
                    ar.version,
                    ar.updated_at
                FROM attendance_records ar
                JOIN team_members tm ON tm.id = ar.member_id
                WHERE ar.session_id = ?
                ORDER BY
                    CASE tm.position
                        WHEN 'GOL' THEN 1
                        ELSE 2
                    END,
                    tm.name COLLATE NOCASE
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_records(
        self,
        session_id: int,
        updates: Iterable[dict[str, Any]],
        *,
        source: str = "ui",
    ) -> int:
        valid_statuses = set(CONFIRMATION_LABELS)
        changed = 0
        now = _now_iso()

        with self.connection() as conn:
            session = conn.execute(
                "SELECT is_finalized FROM training_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise KeyError(f"Treino {session_id} não encontrado.")

            is_finalized = bool(session["is_finalized"])

            for update in updates:
                member_id = int(update["member_id"])
                new_status = str(update["confirmation_status"])
                if new_status not in valid_statuses:
                    raise ValueError(f"Situação inválida: {new_status}")

                row = conn.execute(
                    """
                    SELECT confirmation_status, present, notes, version
                    FROM attendance_records
                    WHERE session_id = ? AND member_id = ?
                    """,
                    (session_id, member_id),
                ).fetchone()
                if row is None:
                    raise KeyError(
                        f"Registro do atleta {member_id} não encontrado no treino."
                    )

                old_status = row["confirmation_status"]
                old_present = row["present"]
                old_notes = row["notes"] or ""

                requested_present = update.get("present")
                if requested_present is True:
                    new_present: int | None = 1
                elif is_finalized:
                    new_present = 0
                elif old_present == 1 and requested_present is False:
                    # Antes do encerramento, desmarcar volta para "não apurado".
                    new_present = None
                else:
                    new_present = old_present

                new_notes = str(update.get("notes") or "").strip()

                if (
                    old_status == new_status
                    and old_present == new_present
                    and old_notes == new_notes
                ):
                    continue

                conn.execute(
                    """
                    UPDATE attendance_records
                    SET confirmation_status = ?,
                        present = ?,
                        notes = ?,
                        version = version + 1,
                        updated_at = ?
                    WHERE session_id = ? AND member_id = ?
                    """,
                    (
                        new_status,
                        new_present,
                        new_notes,
                        now,
                        session_id,
                        member_id,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO attendance_audit_log(
                        session_id, member_id,
                        old_confirmation_status, new_confirmation_status,
                        old_present, new_present,
                        old_notes, new_notes,
                        changed_at, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        member_id,
                        old_status,
                        new_status,
                        old_present,
                        new_present,
                        old_notes,
                        new_notes,
                        now,
                        source,
                    ),
                )
                changed += 1

            conn.execute(
                """
                UPDATE training_sessions
                SET updated_at = ?
                WHERE id = ?
                """,
                (now, session_id),
            )

        return changed

    def sync_records(
        self,
        session_id: int,
        operations: Iterable[dict[str, Any]],
        *,
        source: str = "pwa",
    ) -> list[dict[str, Any]]:
        """Aplica operações idempotentes com controle otimista de versão."""

        valid_statuses = set(CONFIRMATION_LABELS)
        results: list[dict[str, Any]] = []
        now = _now_iso()

        with self.connection() as conn:
            session = conn.execute(
                "SELECT is_finalized FROM training_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise KeyError(f"Treino {session_id} não encontrado.")
            is_finalized = bool(session["is_finalized"])

            for operation in operations:
                normalized = {
                    "operation_id": str(operation["operation_id"]),
                    "member_id": int(operation["member_id"]),
                    "base_version": int(operation["base_version"]),
                    "confirmation_status": str(operation["confirmation_status"]),
                    "present": operation.get("present"),
                    "notes": str(operation.get("notes") or "").strip(),
                }
                if normalized["confirmation_status"] not in valid_statuses:
                    raise ValueError(
                        f"Situação inválida: {normalized['confirmation_status']}"
                    )

                request_json = json.dumps(
                    normalized,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                request_hash = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
                previous = conn.execute(
                    """
                    SELECT request_hash, response_json
                    FROM sync_operations
                    WHERE operation_id = ?
                    """,
                    (normalized["operation_id"],),
                ).fetchone()
                if previous is not None:
                    if previous["request_hash"] != request_hash:
                        raise ValueError(
                            "O identificador da operação já foi usado com outro conteúdo."
                        )
                    results.append(json.loads(previous["response_json"]))
                    continue

                row = conn.execute(
                    """
                    SELECT
                        ar.session_id,
                        ar.member_id,
                        ar.confirmation_status,
                        ar.present,
                        ar.notes,
                        ar.version,
                        ar.updated_at,
                        tm.name,
                        tm.position
                    FROM attendance_records ar
                    JOIN team_members tm ON tm.id = ar.member_id
                    WHERE ar.session_id = ? AND ar.member_id = ?
                    """,
                    (session_id, normalized["member_id"]),
                ).fetchone()
                if row is None:
                    raise KeyError(
                        f"Registro do atleta {normalized['member_id']} não encontrado."
                    )

                if int(row["version"]) != normalized["base_version"]:
                    result = {
                        "operation_id": normalized["operation_id"],
                        "status": "conflict",
                        "record": dict(row),
                    }
                else:
                    requested_present = normalized["present"]
                    if requested_present is True:
                        new_present: int | None = 1
                    elif is_finalized:
                        new_present = 0
                    elif row["present"] == 1 and requested_present is False:
                        new_present = None
                    else:
                        new_present = row["present"]

                    changed = (
                        row["confirmation_status"]
                        != normalized["confirmation_status"]
                        or row["present"] != new_present
                        or (row["notes"] or "") != normalized["notes"]
                    )
                    if changed:
                        conn.execute(
                            """
                            UPDATE attendance_records
                            SET confirmation_status = ?,
                                present = ?,
                                notes = ?,
                                version = version + 1,
                                updated_at = ?
                            WHERE session_id = ? AND member_id = ?
                            """,
                            (
                                normalized["confirmation_status"],
                                new_present,
                                normalized["notes"],
                                now,
                                session_id,
                                normalized["member_id"],
                            ),
                        )
                        conn.execute(
                            """
                            INSERT INTO attendance_audit_log(
                                session_id, member_id,
                                old_confirmation_status, new_confirmation_status,
                                old_present, new_present,
                                old_notes, new_notes,
                                changed_at, source
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                session_id,
                                normalized["member_id"],
                                row["confirmation_status"],
                                normalized["confirmation_status"],
                                row["present"],
                                new_present,
                                row["notes"],
                                normalized["notes"],
                                now,
                                source,
                            ),
                        )
                    else:
                        # Mesmo um no-op aceito consome uma versão. Isso mantém
                        # uma sequência offline de operações causal e previsível.
                        conn.execute(
                            """
                            UPDATE attendance_records
                            SET version = version + 1, updated_at = ?
                            WHERE session_id = ? AND member_id = ?
                            """,
                            (now, session_id, normalized["member_id"]),
                        )
                    refreshed = conn.execute(
                        """
                        SELECT
                            ar.session_id,
                            ar.member_id,
                            ar.confirmation_status,
                            ar.present,
                            ar.notes,
                            ar.version,
                            ar.updated_at,
                            tm.name,
                            tm.position
                        FROM attendance_records ar
                        JOIN team_members tm ON tm.id = ar.member_id
                        WHERE ar.session_id = ? AND ar.member_id = ?
                        """,
                        (session_id, normalized["member_id"]),
                    ).fetchone()
                    result = {
                        "operation_id": normalized["operation_id"],
                        "status": "accepted",
                        "changed": changed,
                        "record": dict(refreshed),
                    }

                response_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
                conn.execute(
                    """
                    INSERT INTO sync_operations(
                        operation_id, request_hash, response_json, created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        normalized["operation_id"],
                        request_hash,
                        response_json,
                        now,
                    ),
                )
                results.append(result)

            conn.execute(
                "UPDATE training_sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )

        return results

    def finalize_session(self, session_id: int, *, source: str = "ui") -> int:
        now = _now_iso()
        changed = 0

        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT member_id, confirmation_status, present, notes, version
                FROM attendance_records
                WHERE session_id = ? AND present IS NULL
                """,
                (session_id,),
            ).fetchall()

            for row in rows:
                conn.execute(
                    """
                    UPDATE attendance_records
                    SET present = 0, version = version + 1, updated_at = ?
                    WHERE session_id = ? AND member_id = ?
                    """,
                    (now, session_id, int(row["member_id"])),
                )
                conn.execute(
                    """
                    INSERT INTO attendance_audit_log(
                        session_id, member_id,
                        old_confirmation_status, new_confirmation_status,
                        old_present, new_present,
                        old_notes, new_notes,
                        changed_at, source
                    )
                    VALUES (?, ?, ?, ?, NULL, 0, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        int(row["member_id"]),
                        row["confirmation_status"],
                        row["confirmation_status"],
                        row["notes"],
                        row["notes"],
                        now,
                        source,
                    ),
                )
                changed += 1

            conn.execute(
                """
                UPDATE training_sessions
                SET is_finalized = 1, updated_at = ?
                WHERE id = ?
                """,
                (now, session_id),
            )

        return changed

    def reopen_session(self, session_id: int) -> None:
        now = _now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE training_sessions
                SET is_finalized = 0, updated_at = ?
                WHERE id = ?
                """,
                (now, session_id),
            )

    def update_session_notes(self, session_id: int, notes: str) -> None:
        now = _now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE training_sessions
                SET notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (notes.strip(), now, session_id),
            )

    def get_history(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    ts.training_date,
                    ts.is_finalized,
                    tm.name,
                    tm.position,
                    ar.confirmation_status,
                    ar.present,
                    ar.notes,
                    ar.version,
                    ar.updated_at
                FROM attendance_records ar
                JOIN training_sessions ts ON ts.id = ar.session_id
                JOIN team_members tm ON tm.id = ar.member_id
                ORDER BY ts.training_date DESC, tm.name COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_audit_log(self, limit: int = 500) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    log.changed_at,
                    ts.training_date,
                    tm.name,
                    tm.position,
                    log.old_confirmation_status,
                    log.new_confirmation_status,
                    log.old_present,
                    log.new_present,
                    log.old_notes,
                    log.new_notes,
                    log.source
                FROM attendance_audit_log log
                JOIN training_sessions ts ON ts.id = log.session_id
                JOIN team_members tm ON tm.id = log.member_id
                ORDER BY log.changed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_members(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM team_members"
        params: tuple[Any, ...] = ()
        if not include_inactive:
            sql += " WHERE active = 1"
        sql += " ORDER BY name COLLATE NOCASE"

        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def add_member(self, name: str, position: str) -> None:
        cleaned_name = name.strip()
        cleaned_position = position.strip().upper()
        if not cleaned_name or not cleaned_position:
            raise ValueError("Nome e posição são obrigatórios.")

        now = _now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO team_members(
                    name, position, active, created_at, updated_at
                )
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    position = excluded.position,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (cleaned_name, cleaned_position, now, now),
            )

    def update_member(self, member_id: int, *, position: str, active: bool) -> None:
        cleaned_position = position.strip().upper()
        if not cleaned_position:
            raise ValueError("A posição não pode ficar vazia.")

        with self.connection() as conn:
            conn.execute(
                """
                UPDATE team_members
                SET position = ?, active = ?, updated_at = ?
                WHERE id = ?
                """,
                (cleaned_position, int(active), _now_iso(), member_id),
            )

    def backup_to(
        self,
        destination: str | Path,
        *,
        pre_migration: bool = False,
        expected_fingerprint: str | None = None,
    ) -> Path:
        """Cria e valida uma cópia consistente sem modificar a origem.

        O modo padrão continua exigindo compatibilidade integral com a aplicação.
        ``pre_migration`` é uma exceção estreita: aceita somente um estado legado
        reconhecido pelo migrador e exige a impressão lógica do plano aprovado.
        """

        destination_path = Path(destination)
        source_status = None
        source_fingerprint = None
        if pre_migration:
            self._validate_physical_integrity()
            source_status = DatabaseMigrator(self.db_path).status()
            recognized_migration_source = (
                not source_status.problems
                and (
                    source_status.state
                    in {"legacy_current", "legacy_requires_migration"}
                    or (
                        source_status.state == "migration_required"
                        and bool(source_status.pending_versions)
                    )
                )
            )
            if not recognized_migration_source:
                raise DatabaseCompatibilityError(
                    "Backup pré-migração recusado: a origem não corresponde "
                    "a um estado legado ou plano de migração reconhecido."
                )
            if not expected_fingerprint:
                raise DatabaseCompatibilityError(
                    "Backup pré-migração exige a impressão lógica do plano."
                )
            source_fingerprint = migration_logical_fingerprint(self.db_path)
            if source_fingerprint != expected_fingerprint:
                raise DatabaseCompatibilityError(
                    "Backup pré-migração recusado: o banco mudou depois do plano."
                )
        else:
            self.validate_existing(quick_check=True)
        if destination_path.exists():
            raise FileExistsError(f"O destino do backup já existe: {destination_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination_path.with_name(
            f".{destination_path.name}.{uuid4().hex}.partial"
        )

        source_uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        source: sqlite3.Connection | None = sqlite3.connect(
            source_uri,
            uri=True,
            timeout=30,
            cached_statements=0,
        )
        target: sqlite3.Connection | None = None
        try:
            target = sqlite3.connect(temporary_path)
            source.backup(target)
            journal_row = _fetchone(target, "PRAGMA journal_mode = DELETE")
            journal_mode = str(journal_row[0] if journal_row else "").lower()
            if journal_mode != "delete":
                raise RuntimeError(
                    "Não foi possível consolidar o backup em arquivo único."
                )
            target.close()
            target = None
            source.close()
            source = None
            backup_repository = AttendanceRepository(temporary_path)
            if pre_migration:
                backup_repository._validate_physical_integrity(immutable=True)
                backup_status = DatabaseMigrator(temporary_path).status()
                if (
                    source_status is None
                    or backup_status.state != source_status.state
                    or backup_status.current_version != source_status.current_version
                    or backup_status.versioned != source_status.versioned
                    or backup_status.pending_versions != source_status.pending_versions
                    or backup_status.problems != source_status.problems
                ):
                    raise DatabaseCompatibilityError(
                        "O backup pré-migração não preservou o estado do esquema."
                    )
                backup_fingerprint = migration_logical_fingerprint(temporary_path)
                if (
                    source_fingerprint is None
                    or backup_fingerprint != source_fingerprint
                    or backup_fingerprint != expected_fingerprint
                ):
                    raise DatabaseCompatibilityError(
                        "O backup pré-migração diverge logicamente da origem."
                    )
            else:
                backup_repository.validate_existing(
                    quick_check=True,
                    immutable=True,
                )
            temporary_path.replace(destination_path)
        except Exception:
            if target is not None:
                target.close()
            if source is not None:
                source.close()
                source = None
            temporary_path.unlink(missing_ok=True)
            raise
        finally:
            if source is not None:
                source.close()
        return destination_path
