from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo

from .models import CONFIRMATION_LABELS, INITIAL_MEMBERS

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _now_iso() -> str:
    return datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")


def _date_iso(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value).isoformat()


class AttendanceRepository:
    """Camada de persistência SQLite do registrador de presenças."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS team_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    position TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS training_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    training_date TEXT NOT NULL UNIQUE,
                    notes TEXT NOT NULL DEFAULT '',
                    is_finalized INTEGER NOT NULL DEFAULT 0
                        CHECK (is_finalized IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS attendance_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    confirmation_status TEXT NOT NULL DEFAULT 'PENDING',
                    present INTEGER NULL CHECK (present IN (0, 1) OR present IS NULL),
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE (session_id, member_id),
                    FOREIGN KEY (session_id) REFERENCES training_sessions(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (member_id) REFERENCES team_members(id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS attendance_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    old_confirmation_status TEXT NULL,
                    new_confirmation_status TEXT NULL,
                    old_present INTEGER NULL,
                    new_present INTEGER NULL,
                    old_notes TEXT NULL,
                    new_notes TEXT NULL,
                    changed_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'ui',
                    FOREIGN KEY (session_id) REFERENCES training_sessions(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (member_id) REFERENCES team_members(id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_attendance_session
                    ON attendance_records(session_id);

                CREATE INDEX IF NOT EXISTS idx_audit_session_changed
                    ON attendance_audit_log(session_id, changed_at);

                CREATE INDEX IF NOT EXISTS idx_training_date
                    ON training_sessions(training_date);
                """
            )

        self.seed_initial_members()

    def seed_initial_members(self) -> None:
        now = _now_iso()
        with self.connection() as conn:
            for name, position in INITIAL_MEMBERS:
                conn.execute(
                    """
                    INSERT INTO team_members(name, position, active, created_at, updated_at)
                    VALUES (?, ?, 1, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        position = excluded.position,
                        updated_at = excluded.updated_at
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
                    SELECT confirmation_status, present, notes
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

    def finalize_session(self, session_id: int, *, source: str = "ui") -> int:
        now = _now_iso()
        changed = 0

        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT member_id, confirmation_status, present, notes
                FROM attendance_records
                WHERE session_id = ? AND present IS NULL
                """,
                (session_id,),
            ).fetchall()

            for row in rows:
                conn.execute(
                    """
                    UPDATE attendance_records
                    SET present = 0, updated_at = ?
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
