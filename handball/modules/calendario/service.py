from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from handball.core.authorization import AccessContext, Permission
from handball.core.calendar import (
    CalendarEventStatus,
    CalendarEventType,
    CollectiveRestrictionKind,
)
from handball.core.errors import CalendarProblem
from handball.core.team_theme import team_theme
from handball.database.contracts import UnitOfWorkFactoryContract

from .schemas import (
    CalendarActionInput,
    CalendarConflictCheckInput,
    CalendarEventInput,
    CalendarRescheduleInput,
    CalendarSeriesEditInput,
    CalendarSeriesInput,
)


LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
ACTIVE_SEASON_LABEL = "2026.2"


class CalendarService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactoryContract,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    @staticmethod
    def _require(context: AccessContext, permission: Permission) -> None:
        if permission not in context.permissions:
            raise PermissionError("Operação não autorizada.")

    @staticmethod
    def _team_ids(context: AccessContext, team_id: int | None = None) -> tuple[int, ...]:
        allowed = tuple(sorted(int(value) for value in context.team_ids))
        if not allowed:
            raise PermissionError("Conta sem equipe ativa.")
        if team_id is not None:
            if int(team_id) not in allowed:
                raise PermissionError("Equipe fora do escopo da conta.")
            return (int(team_id),)
        return allowed

    @staticmethod
    def _to_utc(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=LOCAL_TIMEZONE)
        return value.astimezone(UTC).isoformat(timespec="seconds")

    def options(self, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_READ_TEAM)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            result = unit_of_work.calendar.list_options(self._team_ids(context))
        result.update(
            active_season_label=ACTIVE_SEASON_LABEL,
            event_types=[value.value for value in CalendarEventType],
            statuses=[value.value for value in CalendarEventStatus],
            restriction_kinds=[value.value for value in CollectiveRestrictionKind],
        )
        for team in result["teams"]:
            team["visual_identity"] = team_theme(str(team.get("slug"))).to_dict()
        return result

    def calendar(
        self,
        context: AccessContext,
        *,
        team_id: int | None = None,
        season_id: int | None = None,
        season_label: str | None = None,
        starts_from: str | None = None,
        ends_to: str | None = None,
        event_types: Iterable[str] = (),
        statuses: Iterable[str] = (),
        query: str | None = None,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_READ_TEAM)
        allowed = self._team_ids(context, team_id)
        effective_season_label = (
            None if season_id is not None else season_label or ACTIVE_SEASON_LABEL
        )
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            events = unit_of_work.calendar.list_events(
                allowed,
                season_id=season_id,
                season_label=effective_season_label,
                starts_from=starts_from,
                ends_to=ends_to,
                event_types=event_types,
                statuses=statuses,
                query=query,
            )
            justifications = (
                unit_of_work.calendar.list_justifications(
                    player_member_id=context.linked_player_id,
                    team_ids=allowed,
                )
                if (
                    context.linked_player_id is not None
                    and Permission.CALENDAR_JUSTIFICATION_SELF
                    in context.permissions
                )
                else []
            )
        own_by_event = {int(item["event_id"]): item for item in justifications}
        now = self._now_factory().astimezone(UTC)
        groups: dict[str, list[dict[str, Any]]] = {
            "past": [],
            "present": [],
            "future": [],
        }
        next_player_training_id = next(
            (
                int(event["id"])
                for event in events
                if event["event_type"] == "TRAINING"
                and event["status"] in {"PLANNED", "CONFIRMED"}
                and datetime.fromisoformat(str(event["ends_at"])).astimezone(UTC)
                >= now
            ),
            None,
        )
        decorated_events: list[dict[str, Any]] = []
        for event in events:
            starts_at = datetime.fromisoformat(str(event["starts_at"])).astimezone(UTC)
            ends_at = datetime.fromisoformat(str(event["ends_at"])).astimezone(UTC)
            if ends_at < now:
                period = "past"
            elif starts_at <= now <= ends_at:
                period = "present"
            else:
                period = "future"
            item = dict(event)
            item["period"] = period
            item["own_justification"] = own_by_event.get(int(event["id"]))
            item.update(
                self._event_presentation(
                    item,
                    context,
                    next_player_training_id=next_player_training_id,
                )
            )
            groups[period].append(item)
            decorated_events.append(item)
        return {
            "season_id": season_id,
            "season_label": effective_season_label or ACTIVE_SEASON_LABEL,
            "generated_at": now.isoformat(timespec="seconds"),
            "items": decorated_events,
            "groups": groups,
            "own_justifications": justifications,
        }

    @staticmethod
    def _event_title(event: Mapping[str, Any]) -> str:
        if str(event.get("title") or "").strip():
            return str(event["title"]).strip()
        labels = {
            "TRAINING": "Treino",
            "GAME": "Jogo",
            "CHAMPIONSHIP": "Campeonato",
            "MILESTONE_HOLIDAY": "Marco / feriado",
            "COLLECTIVE_RESTRICTION": "Restrição coletiva",
            "CANCELLATION_RESCHEDULING": "Cancelamento / remarcação",
        }
        title = labels.get(str(event["event_type"]), str(event["event_type"]))
        opponent = str(event.get("opponent") or "").strip()
        return f"{title} × {opponent}" if opponent else title

    def _event_presentation(
        self,
        event: Mapping[str, Any],
        context: AccessContext,
        *,
        next_player_training_id: int | None,
    ) -> dict[str, Any]:
        status = str(event["status"])
        event_type = str(event["event_type"])
        attendance_id = event.get("attendance_session_id")
        attendance_open = bool(attendance_id) and not bool(
            event.get("attendance_is_finalized")
        )
        can_finalize_attendance = bool(
            attendance_open
            and Permission.ATTENDANCE_WRITE in context.permissions
            and Permission.ATTENDANCE_FINALIZE in context.permissions
        )
        actions: list[str] = ["view"]
        primary_action = "view"
        if Permission.CALENDAR_MANAGE in context.permissions:
            if status == "PLANNED":
                actions.extend(["confirm", "edit", "duplicate", "reschedule", "cancel"])
                primary_action = "confirm"
            elif status == "CONFIRMED":
                actions.extend(["edit", "duplicate", "reschedule", "cancel"])
                if event_type != "TRAINING":
                    actions.append("complete")
                    primary_action = "complete"
                elif attendance_id is None:
                    primary_action = "create_attendance"
                elif attendance_open:
                    primary_action = "open_attendance"
                    if can_finalize_attendance:
                        actions.append("finish_training")
                else:
                    actions.append("complete")
                    primary_action = "complete"
            elif status == "CANCELLED":
                actions.extend(["undo_cancel", "duplicate", "history"])
                primary_action = "undo_cancel"
            elif status == "RESCHEDULED":
                actions.extend(["duplicate", "history"])
                primary_action = "history"
            else:
                actions.extend(["duplicate", "history"])
                primary_action = "history"
            if event_type == "TRAINING" and status in {"PLANNED", "CONFIRMED"}:
                action = "open_attendance" if attendance_id else "create_attendance"
                if action not in actions:
                    actions.append(action)
        elif (
            Permission.CALENDAR_JUSTIFICATION_SELF in context.permissions
            and event_type in {"TRAINING", "GAME"}
        ):
            actions.append("justify")
            if int(event["id"]) == next_player_training_id and event_type == "TRAINING":
                actions.append("respond")
                primary_action = "respond"
            else:
                primary_action = "justify"
        return {
            "display_title": self._event_title(event),
            "available_actions": actions,
            "primary_action": primary_action,
            "is_next_player_training": int(event["id"]) == next_player_training_id,
            "can_view_attendance": bool(
                attendance_id
                and Permission.ATTENDANCE_READ_TEAM in context.permissions
            ),
            "can_finalize_attendance": can_finalize_attendance,
        }

    def _event_payload(
        self,
        body: CalendarEventInput,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._team_ids(context, body.team_id)
        return {
            **body.model_dump(mode="json"),
            "starts_at": self._to_utc(body.starts_at),
            "ends_at": self._to_utc(body.ends_at),
        }

    @staticmethod
    def _request_hash(payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def create_event(
        self,
        body: CalendarEventInput,
        context: AccessContext,
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_MANAGE)
        payload = self._event_payload(body, context)
        with self._unit_of_work_factory() as unit_of_work:
            request_hash = self._request_hash(payload)
            if operation_id:
                existing = unit_of_work.calendar.get_command_receipt(
                    operation_id,
                    actor_user_id=context.user_id,
                    request_hash=request_hash,
                )
                if existing is not None:
                    return existing
            created = unit_of_work.calendar.create_event(
                payload,
                actor_user_id=context.user_id,
            )
            if operation_id:
                unit_of_work.calendar.store_command_receipt(
                    operation_id,
                    actor_user_id=context.user_id,
                    request_hash=request_hash,
                    response=created,
                )
            return created

    def update_event(
        self,
        event_id: int,
        body: CalendarEventInput,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_MANAGE)
        allowed = self._team_ids(context, body.team_id)
        payload = self._event_payload(body, context)
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.calendar.get_event(event_id, allowed) is None:
                raise KeyError("Evento não encontrado na equipe autorizada.")
            return unit_of_work.calendar.update_event(
                event_id,
                payload,
                actor_user_id=context.user_id,
            )

    def check_conflicts(
        self,
        body: CalendarConflictCheckInput,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_MANAGE)
        allowed = self._team_ids(context, body.team_id)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            items = unit_of_work.calendar.check_conflicts(
                allowed,
                team_id=body.team_id,
                starts_at=self._to_utc(body.starts_at),
                ends_at=self._to_utc(body.ends_at),
                event_id=body.event_id,
            )
        return {"has_conflicts": bool(items), "items": items}

    def transition_event(
        self,
        event_id: int,
        action: str,
        body: CalendarActionInput,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_MANAGE)
        if action not in {"CONFIRM", "COMPLETE", "CANCEL", "UNDO_CANCEL"}:
            raise CalendarProblem(
                code="calendar.invalid_action",
                title="Ação desconhecida",
                message="O calendário não reconheceu esta ação.",
                suggestion="Recarregue a página e tente novamente.",
            )
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.calendar.transition_event(
                event_id,
                action=action,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
                reason=body.reason,
                base_version=body.base_version,
            )

    def reschedule_event(
        self,
        event_id: int,
        body: CalendarRescheduleInput,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.calendar.reschedule_event(
                event_id,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
                starts_at=self._to_utc(body.starts_at),
                ends_at=self._to_utc(body.ends_at),
                reason=body.reason,
                base_version=body.base_version,
            )

    def event_history(
        self,
        event_id: int,
        context: AccessContext,
    ) -> list[dict[str, Any]]:
        self._require(context, Permission.CALENDAR_READ_TEAM)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.calendar.event_history(
                event_id,
                team_ids=self._team_ids(context),
            )

    def _series_occurrences(
        self,
        body: CalendarSeriesInput,
        context: AccessContext,
    ) -> list[dict[str, Any]]:
        self._team_ids(context, body.team_id)
        values: list[dict[str, Any]] = []
        current = body.starts_on
        while current <= body.ends_on:
            if current.weekday() in body.weekdays:
                local_start = datetime.combine(
                    current,
                    body.start_time,
                    tzinfo=LOCAL_TIMEZONE,
                )
                local_end = local_start + timedelta(minutes=body.duration_minutes)
                values.append(
                    {
                        "team_id": body.team_id,
                        "season_id": body.season_id,
                        "event_type": body.event_type.value,
                        "status": "PLANNED",
                        "starts_at": self._to_utc(local_start),
                        "ends_at": self._to_utc(local_end),
                        "location": body.location,
                        "notes": body.notes,
                        "title": body.title,
                        "opponent": body.opponent,
                        "all_day": False,
                        "restriction_kind": (
                            body.restriction_kind.value
                            if body.restriction_kind
                            else None
                        ),
                        "attendance_session_id": None,
                    }
                )
            current += timedelta(days=1)
        if not values:
            raise CalendarProblem(
                code="calendar.empty_series",
                title="Nenhuma data foi gerada",
                message="Os dias escolhidos não ocorrem dentro do período informado.",
                suggestion="Ajuste o período ou marque outros dias da semana.",
                field="weekdays",
            )
        if len(values) > 160:
            raise CalendarProblem(
                code="calendar.series_too_large",
                title="Série muito grande",
                message="A série geraria mais de 160 eventos.",
                suggestion="Reduza o período e crie duas séries menores.",
                field="ends_on",
            )
        return values

    def preview_series(
        self,
        body: CalendarSeriesInput,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_MANAGE)
        occurrences = self._series_occurrences(body, context)
        conflicts: list[dict[str, Any]] = []
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            for occurrence in occurrences:
                matches = unit_of_work.calendar.check_conflicts(
                    self._team_ids(context, body.team_id),
                    team_id=body.team_id,
                    starts_at=str(occurrence["starts_at"]),
                    ends_at=str(occurrence["ends_at"]),
                )
                if matches:
                    conflicts.append(
                        {
                            "starts_at": occurrence["starts_at"],
                            "items": matches,
                        }
                    )
        return {
            "count": len(occurrences),
            "occurrences": occurrences,
            "conflicts": conflicts,
        }

    def create_series(
        self,
        body: CalendarSeriesInput,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_MANAGE)
        occurrences = self._series_occurrences(body, context)
        preview = self.preview_series(body, context)
        if preview["conflicts"]:
            raise CalendarProblem(
                code="calendar.series_conflict",
                title="A série possui conflitos",
                message="Um ou mais horários coincidem com eventos existentes.",
                suggestion="Revise a prévia e ajuste os dias ou horários.",
                status_code=409,
            )
        payload = body.model_dump(mode="json")
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.calendar.create_series(
                payload,
                occurrences,
                actor_user_id=context.user_id,
            )

    def update_series(
        self,
        series_id: int,
        body: CalendarSeriesEditInput,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_MANAGE)
        payload = self._event_payload(body, context)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.calendar.update_series(
                series_id,
                payload,
                scope=body.scope,
                anchor_event_id=body.anchor_event_id,
                team_ids=self._team_ids(context, body.team_id),
                actor_user_id=context.user_id,
            )

    def save_own_justification(
        self,
        event_id: int,
        reason: str,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_JUSTIFICATION_SELF)
        if context.linked_player_id is None:
            raise PermissionError("Conta sem vínculo com atleta.")
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.calendar.upsert_justification(
                event_id,
                player_member_id=context.linked_player_id,
                user_id=context.user_id,
                reason=reason,
                team_ids=self._team_ids(context),
            )

    def update_own_justification(
        self,
        justification_id: int,
        reason: str,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_JUSTIFICATION_SELF)
        if context.linked_player_id is None:
            raise PermissionError("Conta sem vínculo com atleta.")
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.calendar.update_justification(
                justification_id,
                player_member_id=context.linked_player_id,
                user_id=context.user_id,
                reason=reason,
                team_ids=self._team_ids(context),
            )
