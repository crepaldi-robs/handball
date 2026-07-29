from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from handball.core.authorization import AccessContext, Permission
from handball.database.contracts import UnitOfWorkFactoryContract
from handball.database.manager import DatabaseManager
from handball.database.migrations import fingerprint_from_connection
from handball.database.repositories.sql_explorer import simulate_change


class SqlChangeConflict(RuntimeError):
    """A prévia deixou de representar o estado atual do banco."""


@dataclass(frozen=True)
class _ChangeTicket:
    user_id: int
    session_id: str
    sql: str
    sql_hash: str
    fingerprint: str
    expires_at: float
    preview: dict[str, Any]


@dataclass(frozen=True)
class _TerminalChange:
    user_id: int
    session_id: str
    expires_at: float
    result: dict[str, Any]


class SqlExplorerService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactoryContract,
        database_manager: DatabaseManager,
        *,
        ticket_ttl_seconds: int = 120,
        terminal_ttl_seconds: int = 600,
        max_tickets: int = 256,
        max_tickets_per_session: int = 8,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._database_manager = database_manager
        self._ticket_ttl_seconds = max(30, int(ticket_ttl_seconds))
        self._terminal_ttl_seconds = max(120, int(terminal_ttl_seconds))
        self._max_tickets = max(16, int(max_tickets))
        self._max_tickets_per_session = max(1, int(max_tickets_per_session))
        self._tickets: dict[str, _ChangeTicket | _TerminalChange] = {}
        self._inflight: set[str] = set()
        self._tickets_lock = threading.Lock()

    @staticmethod
    def _access(context: AccessContext, *, admin: bool = False) -> None:
        required = Permission.SQL_ADMIN if admin else Permission.SQL_EXPLORE
        if required not in context.permissions and not (
            not admin and Permission.SQL_ADMIN in context.permissions
        ):
            raise PermissionError("Operação não autorizada.")

    @staticmethod
    def _request_id(token: str) -> str:
        # O token possui 256 bits aleatórios e nunca é persistido. Seu hash
        # permite localizar o resultado sem permitir reconstruir ou forjar o token.
        return "sql-" + hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _session_hash(session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    def _recover_committed_result(
        self, context: AccessContext, *, request_id: str
    ) -> dict[str, Any] | None:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            payload = unit_of_work.identity.get_security_audit_result(
                request_id=request_id,
                actor_user_id=context.user_id,
            )
        if payload is None:
            return None
        expected_session = self._session_hash(context.session_id)
        observed_session = payload.get("session_sha256")
        if not isinstance(observed_session, str) or not secrets.compare_digest(
            observed_session, expected_session
        ):
            return None
        result = payload.get("result")
        if (
            not isinstance(result, dict)
            or result.get("request_id") != request_id
            or result.get("executed") is not True
        ):
            return None
        return {**result, "replayed": True}

    def catalog(self, context: AccessContext) -> dict[str, Any]:
        self._access(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.sql_explorer.catalog()

    def query(
        self, context: AccessContext, *, sql: str, page: int, page_size: int
    ) -> dict[str, Any]:
        self._access(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.sql_explorer.preview(
                sql, page=page, page_size=page_size, allow_write=False
            )

    def explain(self, context: AccessContext, *, sql: str) -> list[dict[str, Any]]:
        self._access(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.sql_explorer.explain(sql)

    def export(self, context: AccessContext, *, sql: str, format: str) -> Path:
        self._access(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            if format == "csv":
                return unit_of_work.sql_explorer.export_csv(sql)
            if format == "xlsx":
                return unit_of_work.sql_explorer.export_xlsx(sql)
        raise ValueError("Formato de exportação inválido.")

    def preview_change(self, context: AccessContext, *, sql: str) -> dict[str, Any]:
        self._access(context, admin=True)
        source_fingerprint = self._database_manager.logical_fingerprint()
        result = simulate_change(self._database_manager, sql)

        token = secrets.token_urlsafe(32)
        expires_at = time.monotonic() + self._ticket_ttl_seconds
        ticket = _ChangeTicket(
            user_id=context.user_id,
            session_id=context.session_id,
            sql=sql,
            sql_hash=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            fingerprint=source_fingerprint,
            expires_at=expires_at,
            preview=result,
        )
        with self._tickets_lock:
            now = time.monotonic()
            self._tickets = {
                key: value for key, value in self._tickets.items()
                if value.expires_at > now
            }
            active_for_session = sum(
                isinstance(value, _ChangeTicket)
                and value.session_id == context.session_id
                for value in self._tickets.values()
            )
            if active_for_session >= self._max_tickets_per_session:
                raise ValueError(
                    "Há muitas prévias pendentes nesta sessão; confirme ou aguarde a expiração."
                )
            if len(self._tickets) >= self._max_tickets:
                raise ValueError(
                    "O limite temporário de prévias foi atingido; tente novamente mais tarde."
                )
            self._tickets[token] = ticket
        return {
            **result,
            "token": token,
            "expires_in_seconds": self._ticket_ttl_seconds,
        }

    def execute_change(self, context: AccessContext, *, token: str) -> dict[str, Any]:
        self._access(context, admin=True)
        request_id = self._request_id(token)
        with self._tickets_lock:
            ticket = self._tickets.get(token)
            if isinstance(ticket, _TerminalChange):
                if ticket.expires_at <= time.monotonic():
                    self._tickets.pop(token, None)
                    ticket = None
                else:
                    if (
                        ticket.user_id != context.user_id
                        or ticket.session_id != context.session_id
                    ):
                        raise PermissionError("A confirmação pertence a outra sessão.")
                    return {**ticket.result, "replayed": True}
            if token in self._inflight:
                raise SqlChangeConflict(
                    "A alteração já está sendo confirmada; aguarde e repita a consulta."
                )
            if isinstance(ticket, _ChangeTicket):
                self._inflight.add(token)
        if ticket is None:
            recovered = self._recover_committed_result(
                context, request_id=request_id
            )
            if recovered is not None:
                return recovered
            raise SqlChangeConflict("A prévia é inválida ou já foi utilizada.")
        if not isinstance(ticket, _ChangeTicket):
            raise SqlChangeConflict("A prévia é inválida.")
        if ticket.expires_at <= time.monotonic():
            with self._tickets_lock:
                self._tickets.pop(token, None)
                self._inflight.discard(token)
            raise SqlChangeConflict("A prévia venceu; analise novamente.")
        if ticket.user_id != context.user_id or ticket.session_id != context.session_id:
            with self._tickets_lock:
                self._inflight.discard(token)
            raise PermissionError("A prévia pertence a outra sessão.")
        committed = False
        try:
            current_fingerprint = self._database_manager.logical_fingerprint()
            if current_fingerprint != ticket.fingerprint:
                raise SqlChangeConflict(
                    "O banco mudou desde a prévia; analise novamente."
                )

            backup_path, backup_hash = self._database_manager.create_sql_change_backup(
                request_id,
                expected_fingerprint=ticket.fingerprint,
            )

            with self._unit_of_work_factory() as unit_of_work:
                if (
                    fingerprint_from_connection(unit_of_work.connection)
                    != ticket.fingerprint
                ):
                    raise SqlChangeConflict("O banco mudou durante a confirmação.")
                result = unit_of_work.sql_explorer.apply_change(ticket.sql)
                response = {
                    **result,
                    "executed": True,
                    "request_id": request_id,
                    "backup_id": backup_path.name,
                    "backup_sha256": backup_hash,
                    "replayed": False,
                }
                unit_of_work.identity.audit_event(
                    actor_user_id=context.user_id,
                    action="sql.change.execute",
                    entity=",".join(result["tables"]) or "database",
                    target_id=None,
                    origin="sql-admin",
                    after={
                        "sql_sha256": ticket.sql_hash,
                        "operation": result["operation"],
                        "preview_affected_rows": ticket.preview["affected_rows"],
                        "affected_rows": result["affected_rows"],
                        "backup_filename": backup_path.name,
                        "backup_sha256": backup_hash,
                        "session_sha256": self._session_hash(context.session_id),
                        "result": response,
                    },
                    request_id=request_id,
                )
                unit_of_work.commit()
            # Grave o terminal antes de qualquer trabalho pós-commit. Se a
            # resposta se perder, repetir o mesmo token devolve este resultado.
            with self._tickets_lock:
                self._tickets[token] = _TerminalChange(
                    user_id=context.user_id,
                    session_id=context.session_id,
                    expires_at=time.monotonic() + self._terminal_ttl_seconds,
                    result=response,
                )
                self._inflight.discard(token)
            committed = True
            self._database_manager.finalize_sql_change_backup(
                backup_path,
                {
                    "request_id": request_id,
                    "backup_filename": backup_path.name,
                    "backup_sha256": backup_hash,
                    "sql_sha256": ticket.sql_hash,
                    "operation": result["operation"],
                    "tables": result["tables"],
                    "affected_rows": result["affected_rows"],
                },
            )
            return response
        except Exception:
            with self._tickets_lock:
                if not committed:
                    self._tickets.pop(token, None)
                self._inflight.discard(token)
            raise
