"""Operações administrativas excepcionais, fora do Explorador SQL.

Estas operações existem para corrigir dados legados que o Explorador SQL deve
recusar: ele nunca pode apagar a trilha de auditoria por uma instrução livre.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

from handball.database.manager import DatabaseManager
from handball.database.migrations import fingerprint_from_connection


@dataclass(frozen=True)
class LegacyTrainingRemoval:
    session_id: int
    training_date: str
    attendance_records: int
    attendance_audit_rows: int


def _normalized_dates(dates: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(sorted({str(value).strip() for value in dates if str(value).strip()}))
    if not normalized:
        raise ValueError("Informe ao menos uma data de treino legado.")
    for value in normalized:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Data inválida: {value!r}. Use AAAA-MM-DD.") from exc
    return normalized


def _request_id(dates: tuple[str, ...]) -> str:
    payload = ",".join(dates).encode("ascii")
    return "maintenance-legacy-training-" + hashlib.sha256(payload).hexdigest()


def _load_targets(connection: Any, dates: tuple[str, ...]) -> list[LegacyTrainingRemoval]:
    placeholders = ",".join("?" for _ in dates)
    linked = connection.execute(
        f"""SELECT ce.id,ce.attendance_session_id
              FROM calendar_events ce
             WHERE ce.attendance_session_id IN (
                 SELECT id FROM training_sessions WHERE training_date IN ({placeholders})
             )""",
        dates,
    ).fetchall()
    if linked:
        ids = ", ".join(str(row["id"]) for row in linked)
        raise ValueError(
            "A remoção administrativa recusou chamadas ligadas ao calendário "
            f"(eventos {ids}). Cancele-as pelo Calendário."
        )
    rows = connection.execute(
        f"""SELECT ts.id,ts.training_date,
                   COUNT(DISTINCT ar.id) AS attendance_records,
                   COUNT(DISTINCT al.id) AS attendance_audit_rows
              FROM training_sessions ts
              LEFT JOIN attendance_records ar ON ar.session_id=ts.id
              LEFT JOIN attendance_audit_log al ON al.session_id=ts.id
             WHERE ts.training_date IN ({placeholders})
             GROUP BY ts.id,ts.training_date
             ORDER BY ts.training_date,ts.id""",
        dates,
    ).fetchall()
    found_dates = {str(row["training_date"]) for row in rows}
    missing = sorted(set(dates) - found_dates)
    duplicated = sorted(
        date for date in found_dates if sum(str(row["training_date"]) == date for row in rows) != 1
    )
    if missing or duplicated:
        problems: list[str] = []
        if missing:
            problems.append("ausentes: " + ", ".join(missing))
        if duplicated:
            problems.append("mais de uma chamada: " + ", ".join(duplicated))
        raise ValueError("Pré-condição de remoção não atendida (" + "; ".join(problems) + ").")
    return [
        LegacyTrainingRemoval(
            session_id=int(row["id"]),
            training_date=str(row["training_date"]),
            attendance_records=int(row["attendance_records"]),
            attendance_audit_rows=int(row["attendance_audit_rows"]),
        )
        for row in rows
    ]


def preview_legacy_training_removal(
    manager: DatabaseManager, *, dates: Iterable[str]
) -> dict[str, Any]:
    """Calcula o impacto sem alterar a base persistente."""
    normalized = _normalized_dates(dates)
    with manager.read_only_connection() as connection:
        targets = _load_targets(connection, normalized)
    items = [asdict(target) for target in targets]
    return {
        "dates": list(normalized),
        "sessions": items,
        "session_count": len(items),
        "attendance_records": sum(item["attendance_records"] for item in items),
        "attendance_audit_rows": sum(item["attendance_audit_rows"] for item in items),
        "request_id": _request_id(normalized),
    }


def execute_legacy_training_removal(
    manager: DatabaseManager,
    *,
    dates: Iterable[str],
    actor_username: str,
) -> dict[str, Any]:
    """Remove chamadas legadas auditadamente após backup e verificações SQLite."""
    normalized = _normalized_dates(dates)
    request_id = _request_id(normalized)
    with manager.unit_of_work(read_only=True) as unit_of_work:
        actor = unit_of_work.identity.get_user_by_username(actor_username)
        if actor is None or not bool(actor["active"]):
            raise ValueError("O usuário auditor não existe ou está inativo.")
        existing = unit_of_work.connection.execute(
            """SELECT after_json FROM security_audit_events
               WHERE request_id=? AND actor_user_id=?
                 AND action='maintenance.legacy_training.remove'
                 AND origin='maintenance-script'
               ORDER BY id DESC LIMIT 1""",
            (request_id, int(actor["id"])),
        ).fetchone()
    if existing is not None and existing["after_json"]:
        payload = json.loads(str(existing["after_json"]))
        if isinstance(payload, dict):
            return {**payload, "replayed": True}

    preview = preview_legacy_training_removal(manager, dates=normalized)
    fingerprint = manager.logical_fingerprint()

    backup_path, backup_sha256 = manager.create_sql_change_backup(
        request_id, expected_fingerprint=fingerprint
    )
    result: dict[str, Any]
    try:
        with manager.unit_of_work() as unit_of_work:
            if fingerprint_from_connection(unit_of_work.connection) != fingerprint:
                raise RuntimeError("O banco mudou depois da prévia; execute uma nova prévia.")
            actor = unit_of_work.identity.get_user_by_username(actor_username)
            if actor is None or not bool(actor["active"]):
                raise ValueError("O usuário auditor não existe ou está inativo.")
            targets = _load_targets(unit_of_work.connection, normalized)
            if [asdict(target) for target in targets] != preview["sessions"]:
                raise RuntimeError("Os alvos mudaram depois da prévia; execute uma nova prévia.")
            identifiers = tuple(target.session_id for target in targets)
            placeholders = ",".join("?" for _ in identifiers)
            deleted = unit_of_work.connection.execute(
                f"DELETE FROM training_sessions WHERE id IN ({placeholders})", identifiers
            ).rowcount
            if deleted != len(targets):
                raise RuntimeError("A remoção não afetou todas as chamadas previstas.")
            quick_check = [str(row[0]) for row in unit_of_work.connection.execute("PRAGMA quick_check")]
            foreign_keys = list(unit_of_work.connection.execute("PRAGMA foreign_key_check"))
            if quick_check != ["ok"] or foreign_keys:
                raise RuntimeError("A remoção falhou nas verificações de integridade SQLite.")
            result = {
                **preview,
                "executed": True,
                "replayed": False,
                "backup_id": backup_path.name,
                "backup_sha256": backup_sha256,
                "deleted_sessions": deleted,
                "verified_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            unit_of_work.identity.audit_event(
                actor_user_id=int(actor["id"]),
                action="maintenance.legacy_training.remove",
                entity="training_sessions",
                target_id=",".join(str(target.session_id) for target in targets),
                origin="maintenance-script",
                before={"sessions": preview["sessions"], "dates": list(normalized)},
                after=result,
                request_id=request_id,
            )
            unit_of_work.commit()
    except Exception:
        raise
    manager.finalize_sql_change_backup(
        backup_path,
        {
            "request_id": request_id,
            "operation": "maintenance.legacy_training.remove",
            "dates": list(normalized),
            "deleted_sessions": result["deleted_sessions"],
            "attendance_records": result["attendance_records"],
            "attendance_audit_rows": result["attendance_audit_rows"],
        },
    )
    return result
