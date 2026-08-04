from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from handball.database.contracts import (
    BackupDownload,
    BackupProvider,
    UnitOfWorkFactoryContract,
)

from .domain import CONFIRMATION_LABELS, build_coach_message, summarize_records
from .planner import build_coach_report, render_coach_report

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


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
        records = self._effective_records(records)
        summary = summarize_records(records)
        coach_report = build_coach_report(records)
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
            "coach_report": coach_report,
            "coach_message": build_coach_message(
                training_date,
                records,
                is_finalized=bool(training["is_finalized"]),
            ) + render_coach_report(coach_report),
            "confirmation_labels": CONFIRMATION_LABELS,
        }

    @staticmethod
    def _payload(
        training: dict[str, Any],
        records: list[dict[str, Any]],
        *,
        calendar_event: dict[str, Any] | None,
        exercises: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        records = AttendanceService._effective_records(records)
        summary = summarize_records(records)
        coach_report = build_coach_report(records, exercises)
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
            "coach_report": coach_report,
            "coach_message": build_coach_message(
                date.fromisoformat(str(training["training_date"])),
                records,
                is_finalized=bool(training["is_finalized"]),
            ) + render_coach_report(coach_report),
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

    @staticmethod
    def _allowed_positions(value: str) -> list[str]:
        return list(dict.fromkeys(part.strip().upper() for part in value.replace(",", "/").split("/") if part.strip()))

    @staticmethod
    def _confirmation_code(response: str) -> str:
        return "CONFIRMED_LATE" if response == "GOING" else "CANCELLED_LATE"

    def active_self_confirmation(
        self, *, team_ids: Iterable[int], player_member_id: int, actor_user_id: int
    ) -> dict[str, Any] | None:
        with self._unit_of_work_factory() as unit_of_work:
            event = unit_of_work.calendar.active_training_event(
                team_ids,
                player_visible_only=False,
            )
            if event is None:
                return None
            linked = unit_of_work.calendar.get_or_create_attendance_session(
                int(event["id"]), team_ids=team_ids, actor_user_id=actor_user_id
            )
            record = next(
                item for item in unit_of_work.attendance.get_session_records(int(linked["session"]["id"]))
                if int(item["member_id"]) == int(player_member_id)
            )
            justification = unit_of_work.calendar.own_justification(
                int(event["id"]), player_member_id=player_member_id
            )
        return {
            "event": linked["event"], "session": linked["session"], "record": record,
            "allowed_positions": list(record.get("attack_positions") or self._allowed_positions(str(record["position"]))),
            "justification": justification["reason"] if justification else "",
        }

    def save_self_confirmation(
        self,
        event_id: int,
        *,
        response: str,
        positions: list[str],
        justification: str,
        base_version: int,
        team_ids: Iterable[int],
        player_member_id: int,
        actor_user_id: int,
    ) -> dict[str, Any]:
        with self._unit_of_work_factory() as unit_of_work:
            active = unit_of_work.calendar.active_training_event(
                team_ids,
                player_visible_only=False,
            )
            if active is None or int(active["id"]) != int(event_id):
                raise ValueError("Este não é mais o treino ativo para confirmação.")
            linked = unit_of_work.calendar.get_or_create_attendance_session(
                int(event_id), team_ids=team_ids, actor_user_id=actor_user_id
            )
            records = unit_of_work.attendance.get_session_records(int(linked["session"]["id"]))
            record = next(item for item in records if int(item["member_id"]) == int(player_member_id))
            allowed = set(record.get("attack_positions") or self._allowed_positions(str(record["position"])))
            normalized_positions = [str(value).strip().upper() for value in positions]
            if response == "NOT_GOING" and normalized_positions:
                raise ValueError("Posições só se aplicam quando você vai ao treino.")
            if any(position not in allowed for position in normalized_positions):
                raise ValueError("Selecione apenas posições cadastradas para você.")
            updated = unit_of_work.attendance.update_self_confirmation(
                int(linked["session"]["id"]), member_id=player_member_id,
                confirmation_status=self._confirmation_code(response),
                positions=normalized_positions, base_version=base_version, actor_user_id=actor_user_id,
                training_starts_at=str(linked["event"]["starts_at"]),
            )
            clean_justification = justification.strip()
            if clean_justification:
                unit_of_work.calendar.upsert_justification(
                    int(event_id), player_member_id=player_member_id, user_id=actor_user_id,
                    reason=clean_justification, team_ids=team_ids,
                )
            else:
                unit_of_work.calendar.delete_own_justification(
                    int(event_id), player_member_id=player_member_id, user_id=actor_user_id,
                    team_ids=team_ids,
                )
        return {"event": linked["event"], "session": linked["session"], "record": updated, "justification": clean_justification}

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
            exercises = unit_of_work.playbook.list_published_exercise_specs(team_ids)
        return self._payload(
            linked["session"],
            records,
            calendar_event=linked["event"],
            exercises=exercises,
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
            exercises = unit_of_work.playbook.list_published_exercise_specs(team_ids)
        return self._payload(training, records, calendar_event=calendar_event, exercises=exercises)

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

    def add_member(
        self, name: str, position: str, *, attack_positions: Iterable[str] | None = None,
        defensive_positions: Iterable[str] | None = None, actor_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.attendance.add_member(
                name, position, attack_positions=attack_positions,
                defensive_positions=defensive_positions, actor_user_id=actor_user_id,
            )
            return unit_of_work.attendance.list_members(include_inactive=True)

    def update_member(
        self,
        member_id: int,
        *,
        position: str,
        active: bool,
        attack_positions: Iterable[str] | None = None,
        defensive_positions: Iterable[str] | None = None,
        actor_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.attendance.update_member(
                member_id,
                position=position,
                active=active,
                attack_positions=attack_positions,
                defensive_positions=defensive_positions,
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
    @staticmethod
    def _effective_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for raw in records:
            item = dict(raw)
            selected = list(item.get("training_positions") or ())
            profile = list(item.get("attack_positions") or ())
            item["effective_attack_positions"] = selected or profile
            item["attack_position_source"] = "SELECTED" if selected else ("PROFILE_DEFAULT" if profile else "INCOMPLETE")
            item["defensive_generic"] = not bool(item.get("defensive_positions"))
            result.append(item)
        return result
