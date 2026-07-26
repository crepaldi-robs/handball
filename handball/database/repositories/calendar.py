from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from handball.core.calendar import (
    JUSTIFIABLE_EVENT_TYPES,
    CalendarEventStatus,
    CalendarEventType,
    CollectiveRestrictionKind,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ids(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted({int(value) for value in values if int(value) > 0}))


def _placeholders(values: tuple[int, ...]) -> str:
    return ",".join("?" for _ in values)


class CalendarRepository:
    """SQL do Calendário, sempre dentro da conexão da UnitOfWork."""

    def __init__(self, connection: Any, *, read_only: bool = False) -> None:
        self.connection = connection
        self.read_only = read_only

    def list_options(self, team_ids: Iterable[int]) -> dict[str, list[dict[str, Any]]]:
        allowed = _ids(team_ids)
        if not allowed:
            return {"teams": [], "seasons": []}
        placeholders = _placeholders(allowed)
        teams = self.connection.execute(
            f"""SELECT id,code,slug,display_name
                FROM teams
                WHERE active=1 AND id IN ({placeholders})
                ORDER BY display_name COLLATE NOCASE""",
            allowed,
        ).fetchall()
        seasons = self.connection.execute(
            f"""SELECT s.id,s.team_id,s.label,s.starts_on,s.ends_on,s.active,
                       t.display_name team_name
                FROM seasons s
                JOIN teams t ON t.id=s.team_id
                WHERE s.active=1 AND s.team_id IN ({placeholders})
                ORDER BY s.label DESC,t.display_name COLLATE NOCASE""",
            allowed,
        ).fetchall()
        return {
            "teams": [dict(row) for row in teams],
            "seasons": [dict(row) for row in seasons],
        }

    def list_events(
        self,
        team_ids: Iterable[int],
        *,
        season_id: int | None = None,
        season_label: str | None = None,
    ) -> list[dict[str, Any]]:
        allowed = _ids(team_ids)
        if not allowed:
            return []
        placeholders = _placeholders(allowed)
        parameters: list[Any] = list(allowed)
        season_clause = ""
        if season_id is not None:
            season_clause = " AND e.season_id=?"
            parameters.append(int(season_id))
        elif season_label:
            season_clause = " AND s.label=?"
            parameters.append(season_label)
        rows = self.connection.execute(
            f"""SELECT e.id,e.team_id,e.season_id,e.event_type,e.status,
                       e.starts_at,e.ends_at,e.location,e.notes,e.restriction_kind,
                       e.attendance_session_id,e.created_at,e.updated_at,
                       s.label season_label,s.starts_on season_starts_on,
                       s.ends_on season_ends_on,t.display_name team_name,
                       ts.training_date attendance_training_date
                FROM calendar_events e
                JOIN seasons s ON s.id=e.season_id AND s.team_id=e.team_id
                JOIN teams t ON t.id=e.team_id
                LEFT JOIN training_sessions ts ON ts.id=e.attendance_session_id
                WHERE e.team_id IN ({placeholders}){season_clause}
                ORDER BY e.starts_at,e.ends_at,e.id""",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_event(
        self,
        event_id: int,
        team_ids: Iterable[int],
    ) -> dict[str, Any] | None:
        allowed = _ids(team_ids)
        if not allowed:
            return None
        placeholders = _placeholders(allowed)
        row = self.connection.execute(
            f"""SELECT e.id,e.team_id,e.season_id,e.event_type,e.status,
                       e.starts_at,e.ends_at,e.location,e.notes,e.restriction_kind,
                       e.attendance_session_id,e.created_at,e.updated_at,
                       s.label season_label,t.display_name team_name,
                       ts.training_date attendance_training_date
                FROM calendar_events e
                JOIN seasons s ON s.id=e.season_id AND s.team_id=e.team_id
                JOIN teams t ON t.id=e.team_id
                LEFT JOIN training_sessions ts ON ts.id=e.attendance_session_id
                WHERE e.id=? AND e.team_id IN ({placeholders})""",
            (int(event_id), *allowed),
        ).fetchone()
        return dict(row) if row else None

    def _validate_event_payload(self, payload: Mapping[str, Any]) -> None:
        event_type = CalendarEventType(str(payload["event_type"]))
        status = CalendarEventStatus(str(payload["status"]))
        restriction = payload.get("restriction_kind")
        if event_type is CalendarEventType.COLLECTIVE_RESTRICTION:
            if restriction is None:
                raise ValueError("A restrição coletiva exige um motivo formal.")
            CollectiveRestrictionKind(str(restriction))
        elif restriction is not None:
            raise ValueError("Motivo de restrição só se aplica a restrição coletiva.")
        if (
            event_type is CalendarEventType.CANCELLATION_RESCHEDULING
            and status
            not in {CalendarEventStatus.CANCELLED, CalendarEventStatus.RESCHEDULED}
        ):
            raise ValueError(
                "Cancelamento/remarcação exige status CANCELLED ou RESCHEDULED."
            )
        if payload.get("attendance_session_id") is not None:
            if event_type is not CalendarEventType.TRAINING:
                raise ValueError("Somente treino pode referenciar uma presença.")
            exists = self.connection.execute(
                "SELECT 1 FROM training_sessions WHERE id=?",
                (int(payload["attendance_session_id"]),),
            ).fetchone()
            if not exists:
                raise ValueError("A chamada de presença informada não existe.")
        season = self.connection.execute(
            "SELECT team_id FROM seasons WHERE id=? AND active=1",
            (int(payload["season_id"]),),
        ).fetchone()
        if season is None or int(season["team_id"]) != int(payload["team_id"]):
            raise ValueError("Temporada e equipe não correspondem.")

    def _audit(
        self,
        *,
        actor_user_id: int,
        action: str,
        entity: str,
        target_id: int,
        before: Any = None,
        after: Any = None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO security_audit_events(
                   actor_user_id,occurred_at,action,entity,target_id,origin,
                   before_json,after_json,request_id
               ) VALUES(?,?,?,?,?,'calendar',?,?,NULL)""",
            (
                actor_user_id,
                _now_iso(),
                action,
                entity,
                str(target_id),
                json.dumps(before, ensure_ascii=False, sort_keys=True)
                if before is not None
                else None,
                json.dumps(after, ensure_ascii=False, sort_keys=True)
                if after is not None
                else None,
            ),
        )

    def create_event(
        self,
        payload: Mapping[str, Any],
        *,
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._validate_event_payload(payload)
        now = _now_iso()
        try:
            cursor = self.connection.execute(
                """INSERT INTO calendar_events(
                       team_id,season_id,event_type,status,starts_at,ends_at,
                       location,notes,restriction_kind,attendance_session_id,
                       created_by_user_id,updated_by_user_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(payload["team_id"]),
                    int(payload["season_id"]),
                    str(payload["event_type"]),
                    str(payload["status"]),
                    str(payload["starts_at"]),
                    str(payload["ends_at"]),
                    str(payload.get("location") or ""),
                    str(payload.get("notes") or ""),
                    payload.get("restriction_kind"),
                    payload.get("attendance_session_id"),
                    actor_user_id,
                    actor_user_id,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Evento incompatível com o calendário.") from exc
        event_id = int(cursor.lastrowid)
        event = self.get_event(event_id, [int(payload["team_id"])])
        if event is None:
            raise RuntimeError("Evento criado não pôde ser relido.")
        self._audit(
            actor_user_id=actor_user_id,
            action="calendar.event.create",
            entity="calendar_event",
            target_id=event_id,
            after=event,
        )
        return event

    def update_event(
        self,
        event_id: int,
        payload: Mapping[str, Any],
        *,
        actor_user_id: int,
    ) -> dict[str, Any]:
        before = self.get_event(event_id, [int(payload["team_id"])])
        if before is None:
            raise KeyError("Evento não encontrado na equipe autorizada.")
        self._validate_event_payload(payload)
        try:
            self.connection.execute(
                """UPDATE calendar_events
                   SET team_id=?,season_id=?,event_type=?,status=?,starts_at=?,
                       ends_at=?,location=?,notes=?,restriction_kind=?,
                       attendance_session_id=?,updated_by_user_id=?,updated_at=?
                   WHERE id=?""",
                (
                    int(payload["team_id"]),
                    int(payload["season_id"]),
                    str(payload["event_type"]),
                    str(payload["status"]),
                    str(payload["starts_at"]),
                    str(payload["ends_at"]),
                    str(payload.get("location") or ""),
                    str(payload.get("notes") or ""),
                    payload.get("restriction_kind"),
                    payload.get("attendance_session_id"),
                    actor_user_id,
                    _now_iso(),
                    int(event_id),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Evento incompatível com o calendário.") from exc
        after = self.get_event(event_id, [int(payload["team_id"])])
        if after is None:
            raise RuntimeError("Evento atualizado não pôde ser relido.")
        self._audit(
            actor_user_id=actor_user_id,
            action="calendar.event.update",
            entity="calendar_event",
            target_id=event_id,
            before=before,
            after=after,
        )
        return after

    def list_justifications(
        self,
        *,
        player_member_id: int,
        team_ids: Iterable[int],
    ) -> list[dict[str, Any]]:
        allowed = _ids(team_ids)
        if not allowed:
            return []
        placeholders = _placeholders(allowed)
        rows = self.connection.execute(
            f"""SELECT j.id,j.event_id,j.player_member_id,j.reason,
                       j.created_at,j.updated_at,e.team_id,e.event_type,
                       e.starts_at,e.ends_at,s.label season_label
                FROM calendar_justifications j
                JOIN calendar_events e ON e.id=j.event_id
                JOIN seasons s ON s.id=e.season_id
                WHERE j.player_member_id=?
                  AND e.team_id IN ({placeholders})
                ORDER BY e.starts_at,j.id""",
            (int(player_member_id), *allowed),
        ).fetchall()
        return [dict(row) for row in rows]

    def _owned_justifiable_event(
        self,
        event_id: int,
        *,
        player_member_id: int,
        user_id: int,
        team_ids: Iterable[int],
    ) -> dict[str, Any]:
        allowed = _ids(team_ids)
        if not allowed:
            raise PermissionError("Conta sem equipe ativa.")
        placeholders = _placeholders(allowed)
        row = self.connection.execute(
            f"""SELECT e.id,e.team_id,e.event_type
                FROM calendar_events e
                JOIN player_user_links pul
                  ON pul.team_member_id=? AND pul.user_id=?
                JOIN team_memberships tm
                  ON tm.person_id=pul.person_id
                 AND tm.team_id=e.team_id
                 AND tm.season_id=e.season_id
                 AND tm.status='ACTIVE'
                WHERE e.id=? AND e.team_id IN ({placeholders})""",
            (int(player_member_id), int(user_id), int(event_id), *allowed),
        ).fetchone()
        if row is None:
            raise PermissionError("Evento fora do vínculo ativo do atleta.")
        if CalendarEventType(str(row["event_type"])) not in JUSTIFIABLE_EVENT_TYPES:
            raise ValueError("Justificativas só podem ser registradas em treino ou jogo.")
        return dict(row)

    def upsert_justification(
        self,
        event_id: int,
        *,
        player_member_id: int,
        user_id: int,
        reason: str,
        team_ids: Iterable[int],
    ) -> dict[str, Any]:
        event = self._owned_justifiable_event(
            event_id,
            player_member_id=player_member_id,
            user_id=user_id,
            team_ids=team_ids,
        )
        now = _now_iso()
        before_row = self.connection.execute(
            """SELECT id,event_id,player_member_id,reason,created_at,updated_at
               FROM calendar_justifications
               WHERE event_id=? AND player_member_id=?""",
            (int(event_id), int(player_member_id)),
        ).fetchone()
        self.connection.execute(
            """INSERT INTO calendar_justifications(
                   event_id,player_member_id,reason,created_by_user_id,
                   updated_by_user_id,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(event_id,player_member_id) DO UPDATE SET
                   reason=excluded.reason,
                   updated_by_user_id=excluded.updated_by_user_id,
                   updated_at=excluded.updated_at""",
            (
                int(event_id),
                int(player_member_id),
                reason,
                int(user_id),
                int(user_id),
                now,
                now,
            ),
        )
        row = self.connection.execute(
            """SELECT id,event_id,player_member_id,reason,created_at,updated_at
               FROM calendar_justifications
               WHERE event_id=? AND player_member_id=?""",
            (int(event_id), int(player_member_id)),
        ).fetchone()
        result = dict(row)
        self._audit(
            actor_user_id=user_id,
            action=(
                "calendar.justification.update"
                if before_row
                else "calendar.justification.create"
            ),
            entity="calendar_justification",
            target_id=int(result["id"]),
            before=dict(before_row) if before_row else None,
            after=result,
        )
        result["team_id"] = event["team_id"]
        return result

    def update_justification(
        self,
        justification_id: int,
        *,
        player_member_id: int,
        user_id: int,
        reason: str,
        team_ids: Iterable[int],
    ) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT event_id FROM calendar_justifications
               WHERE id=? AND player_member_id=?""",
            (int(justification_id), int(player_member_id)),
        ).fetchone()
        if row is None:
            raise KeyError("Justificativa própria não encontrada.")
        return self.upsert_justification(
            int(row["event_id"]),
            player_member_id=player_member_id,
            user_id=user_id,
            reason=reason,
            team_ids=team_ids,
        )
