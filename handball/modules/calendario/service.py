from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from handball.core.authorization import AccessContext, Permission
from handball.core.calendar import (
    CalendarEventStatus,
    CalendarEventType,
    CollectiveRestrictionKind,
)
from handball.database.contracts import UnitOfWorkFactoryContract

from .schemas import CalendarEventInput


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
        return result

    def calendar(
        self,
        context: AccessContext,
        *,
        team_id: int | None = None,
        season_id: int | None = None,
        season_label: str | None = None,
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
            groups[period].append(item)
        return {
            "season_id": season_id,
            "season_label": effective_season_label or ACTIVE_SEASON_LABEL,
            "generated_at": now.isoformat(timespec="seconds"),
            "items": events,
            "groups": groups,
            "own_justifications": justifications,
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

    def create_event(
        self,
        body: CalendarEventInput,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.CALENDAR_MANAGE)
        payload = self._event_payload(body, context)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.calendar.create_event(
                payload,
                actor_user_id=context.user_id,
            )

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
