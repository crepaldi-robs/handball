from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from handball.database.contracts import (
    BackupDownload,
    BackupProvider,
    UnitOfWorkFactoryContract,
)

from .domain import CONFIRMATION_LABELS, build_coach_message, summarize_records


class AttendanceService:
    """Caso de uso de presenças sobre contratos centrais de persistência."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactoryContract,
        backup_provider: BackupProvider,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._backup_provider = backup_provider

    def session_payload(
        self,
        training_date: date,
        *,
        actor_user_id: int | None = None,
    ) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            training = unit_of_work.attendance.get_or_create_session(
                training_date, actor_user_id=actor_user_id
            )
            records = unit_of_work.attendance.get_session_records(int(training["id"]))
        summary = summarize_records(records)
        return {
            "session": training,
            "records": records,
            "summary": {
                "confirmed": len(summary["confirmed"]),
                "pending": len(summary["pending"]),
                "cancelled": len(summary["cancelled"]),
                "present": len(summary["present"]),
                "absent": len(summary["absent"]),
                "unknown_presence": len(summary["unknown_presence"]),
            },
            "coach_message": build_coach_message(
                training_date,
                records,
                is_finalized=bool(training["is_finalized"]),
            ),
            "confirmation_labels": CONFIRMATION_LABELS,
        }

    @staticmethod
    def _payload(
        training: dict[str, Any],
        records: list[dict[str, Any]],
        *,
        calendar_event: dict[str, Any] | None,
    ) -> dict[str, Any]:
        summary = summarize_records(records)
        return {
            "session": training,
            "calendar_event": calendar_event,
            "records": records,
            "summary": {
                "confirmed": len(summary["confirmed"]),
                "pending": len(summary["pending"]),
                "cancelled": len(summary["cancelled"]),
                "present": len(summary["present"]),
                "absent": len(summary["absent"]),
                "unknown_presence": len(summary["unknown_presence"]),
            },
            "coach_message": build_coach_message(
                date.fromisoformat(str(training["training_date"])),
                records,
                is_finalized=bool(training["is_finalized"]),
            ),
            "confirmation_labels": CONFIRMATION_LABELS,
        }

    def calendar_trainings(
        self,
        *,
        team_ids: Iterable[int],
        season_id: int | None,
    ) -> list[dict[str, Any]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.calendar.list_training_events(
                team_ids,
                season_id=season_id,
            )

    def open_calendar_training(
        self,
        event_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            linked = unit_of_work.calendar.get_or_create_attendance_session(
                event_id,
                team_ids=team_ids,
                actor_user_id=actor_user_id,
            )
            records = unit_of_work.attendance.get_session_records(
                int(linked["session"]["id"])
            )
        return self._payload(
            linked["session"],
            records,
            calendar_event=linked["event"],
        )

    def calendar_session_payload(
        self,
        session_id: int,
        *,
        team_ids: Iterable[int],
    ) -> dict[str, Any]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            training = unit_of_work.attendance.get_session(session_id)
            calendar_event = unit_of_work.calendar.get_training_event_for_session(
                session_id,
                team_ids,
            )
            if calendar_event is None:
                raise KeyError("Chamada sem vínculo com um treino autorizado.")
            records = unit_of_work.attendance.get_session_records(session_id)
        return self._payload(training, records, calendar_event=calendar_event)

    def sync_records(
        self,
        session_id: int,
        operations: Iterable[dict[str, Any]],
        *,
        offline: bool,
        actor_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        source = "pwa-offline" if offline else "pwa-online"
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.attendance.sync_records(
                session_id,
                operations,
                source=source,
                actor_user_id=actor_user_id,
            )

    def finalize_session(self, session_id: int, *, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            changed = unit_of_work.attendance.finalize_session(
                session_id,
                source="pwa-finalize",
                actor_user_id=actor_user_id,
            )
            training = unit_of_work.attendance.get_session(session_id)
        return {"changed": changed, "session": training}

    def reopen_session(self, session_id: int, *, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.attendance.reopen_session(session_id, source="pwa-reopen", actor_user_id=actor_user_id)
            training = unit_of_work.attendance.get_session(session_id)
        return {"session": training}

    def update_session_notes(self, session_id: int, notes: str, *, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.attendance.update_session_notes(session_id, notes, source="pwa-notes", actor_user_id=actor_user_id)
            training = unit_of_work.attendance.get_session(session_id)
        return {"session": training}

    def history(self) -> list[dict[str, Any]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.attendance.get_history()

    def audit(self, limit: int) -> list[dict[str, Any]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.attendance.get_audit_log(limit=limit)

    def members(self) -> list[dict[str, Any]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.attendance.list_members(include_inactive=True)

    def add_member(self, name: str, position: str, *, actor_user_id: int | None = None) -> list[dict[str, Any]]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.attendance.add_member(name, position, actor_user_id=actor_user_id)
            return unit_of_work.attendance.list_members(include_inactive=True)

    def update_member(
        self,
        member_id: int,
        *,
        position: str,
        active: bool,
        actor_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.attendance.update_member(
                member_id,
                position=position,
                active=active,
                actor_user_id=actor_user_id,
            )
            return unit_of_work.attendance.list_members(include_inactive=True)

    def session_export_rows(
        self,
        session_id: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            training = unit_of_work.attendance.get_session(session_id)
            records = unit_of_work.attendance.get_session_records(session_id)
        return training, [
            {
                "training_date": training["training_date"],
                "is_finalized": training["is_finalized"],
                **record,
            }
            for record in records
        ]

    def create_backup_download(self) -> BackupDownload:
        return self._backup_provider.create_backup_download()
