from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from handball.core.calendar import (
    JUSTIFIABLE_EVENT_TYPES,
    CalendarEventStatus,
    CalendarEventType,
    CollectiveRestrictionKind,
)
from handball.core.errors import CalendarProblem


LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
ATTENDANCE_OPEN_STATUSES = frozenset({"PLANNED", "CONFIRMED"})
ATTENDANCE_LOCKED_STATUSES = frozenset({"CANCELLED", "RESCHEDULED"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ids(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted({int(value) for value in values if int(value) > 0}))


def _placeholders(values: tuple[int, ...]) -> str:
    return ",".join("?" for _ in values)


def _local_date(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(LOCAL_TIMEZONE).date().isoformat()


class CalendarRepository:
    """SQL do Calendário, sempre dentro da conexão da UnitOfWork."""

    def __init__(self, connection: Any, *, read_only: bool = False) -> None:
        self.connection = connection
        self.read_only = read_only

    def _table_exists(self, table: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    def _column_exists(self, table: str, column: str) -> bool:
        return any(
            str(row["name"]) == column
            for row in self.connection.execute(f"PRAGMA table_info({table})")
        )

    def supports_professional_calendar(self) -> bool:
        return (
            self._table_exists("calendar_event_transitions")
            and self._column_exists("calendar_events", "version")
        )

    def supports_countdown_targets(self) -> bool:
        return self._column_exists("calendar_events", "is_countdown_target")

    def supports_player_visibility(self) -> bool:
        return self._column_exists("calendar_events", "is_player_visible")

    def _professional_projection(self) -> str:
        if self.supports_professional_calendar():
            return (
                "e.title,e.opponent,e.all_day,e.version,e.series_id,"
            )
        return (
            "'' AS title,'' AS opponent,0 AS all_day,1 AS version,"
            "NULL AS series_id,"
        )

    def _countdown_projection(self) -> str:
        return (
            "e.is_countdown_target,"
            if self.supports_countdown_targets()
            else "0 AS is_countdown_target,"
        )

    def _player_visibility_projection(self) -> str:
        return (
            "e.is_player_visible,"
            if self.supports_player_visibility()
            else "0 AS is_player_visible,"
        )

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
        starts_from: str | None = None,
        ends_to: str | None = None,
        event_types: Iterable[str] = (),
        statuses: Iterable[str] = (),
        query: str | None = None,
        player_visible_only: bool = False,
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
        filter_clauses: list[str] = []
        if starts_from:
            filter_clauses.append("e.ends_at>=?")
            parameters.append(starts_from)
        if ends_to:
            filter_clauses.append("e.starts_at<=?")
            parameters.append(ends_to)
        type_values = tuple(sorted({str(value) for value in event_types if value}))
        if type_values:
            filter_clauses.append(
                f"e.event_type IN ({_placeholders(tuple(range(len(type_values))))})"
            )
            parameters.extend(type_values)
        status_values = tuple(sorted({str(value) for value in statuses if value}))
        if status_values:
            filter_clauses.append(
                f"e.status IN ({_placeholders(tuple(range(len(status_values))))})"
            )
            parameters.extend(status_values)
        if query and query.strip():
            term = f"%{query.strip()}%"
            if self.supports_professional_calendar():
                filter_clauses.append(
                    "(e.title LIKE ? COLLATE NOCASE OR e.opponent LIKE ? COLLATE NOCASE "
                    "OR e.location LIKE ? COLLATE NOCASE OR e.notes LIKE ? COLLATE NOCASE)"
                )
                parameters.extend((term, term, term, term))
            else:
                filter_clauses.append(
                    "(e.location LIKE ? COLLATE NOCASE OR e.notes LIKE ? COLLATE NOCASE)"
                )
                parameters.extend((term, term))
        if player_visible_only:
            if not self.supports_player_visibility():
                return []
            filter_clauses.append("e.is_player_visible=1")
        filters = "".join(f" AND {clause}" for clause in filter_clauses)
        professional_projection = self._professional_projection()
        countdown_projection = self._countdown_projection()
        visibility_projection = self._player_visibility_projection()
        rows = self.connection.execute(
            f"""SELECT e.id,e.team_id,e.season_id,e.event_type,e.status,
                       e.starts_at,e.ends_at,e.location,e.notes,e.restriction_kind,
                       e.attendance_session_id,e.created_at,e.updated_at,
                       {professional_projection}{countdown_projection}{visibility_projection}
                       s.label season_label,s.starts_on season_starts_on,
                       s.ends_on season_ends_on,t.display_name team_name,
                       ts.training_date attendance_training_date,
                       ts.is_finalized attendance_is_finalized,
                       ts.notes attendance_notes
                FROM calendar_events e
                JOIN seasons s ON s.id=e.season_id AND s.team_id=e.team_id
                JOIN teams t ON t.id=e.team_id
                LEFT JOIN training_sessions ts ON ts.id=e.attendance_session_id
                WHERE e.team_id IN ({placeholders}){season_clause}{filters}
                ORDER BY e.starts_at,e.ends_at,e.id""",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_event(
        self,
        event_id: int,
        team_ids: Iterable[int],
        *,
        player_visible_only: bool = False,
    ) -> dict[str, Any] | None:
        allowed = _ids(team_ids)
        if not allowed:
            return None
        placeholders = _placeholders(allowed)
        professional_projection = self._professional_projection()
        countdown_projection = self._countdown_projection()
        visibility_projection = self._player_visibility_projection()
        if player_visible_only and not self.supports_player_visibility():
            return None
        visible_clause = " AND e.is_player_visible=1" if player_visible_only else ""
        row = self.connection.execute(
            f"""SELECT e.id,e.team_id,e.season_id,e.event_type,e.status,
                       e.starts_at,e.ends_at,e.location,e.notes,e.restriction_kind,
                       e.attendance_session_id,e.created_at,e.updated_at,
                       {professional_projection}{countdown_projection}{visibility_projection}
                       s.label season_label,t.display_name team_name,
                       ts.training_date attendance_training_date,
                       ts.is_finalized attendance_is_finalized,
                       ts.notes attendance_notes
                FROM calendar_events e
                JOIN seasons s ON s.id=e.season_id AND s.team_id=e.team_id
                JOIN teams t ON t.id=e.team_id
                LEFT JOIN training_sessions ts ON ts.id=e.attendance_session_id
                WHERE e.id=? AND e.team_id IN ({placeholders}){visible_clause}""",
            (int(event_id), *allowed),
        ).fetchone()
        return dict(row) if row else None

    def list_training_events(
        self,
        team_ids: Iterable[int],
        *,
        season_id: int | None = None,
        player_visible_only: bool = False,
    ) -> list[dict[str, Any]]:
        allowed = _ids(team_ids)
        if not allowed:
            return []
        placeholders = _placeholders(allowed)
        parameters: list[Any] = [*allowed]
        season_clause = ""
        if season_id is not None:
            season_clause = " AND e.season_id=?"
            parameters.append(int(season_id))
        professional_projection = self._professional_projection()
        countdown_projection = self._countdown_projection()
        visibility_projection = self._player_visibility_projection()
        if player_visible_only and not self.supports_player_visibility():
            return []
        visible_clause = " AND e.is_player_visible=1" if player_visible_only else ""
        rows = self.connection.execute(
            f"""SELECT e.id,e.team_id,e.season_id,e.event_type,e.status,
                       e.starts_at,e.ends_at,e.location,e.notes,
                       e.attendance_session_id,{professional_projection}{countdown_projection}{visibility_projection}
                       s.label season_label,
                       ts.training_date,ts.is_finalized
                FROM calendar_events e
                JOIN seasons s ON s.id=e.season_id AND s.team_id=e.team_id
                LEFT JOIN training_sessions ts ON ts.id=e.attendance_session_id
                WHERE e.event_type='TRAINING' AND e.team_id IN ({placeholders})
                      {season_clause}{visible_clause}
                ORDER BY e.starts_at,e.id""",
            parameters,
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["training_date"] = _local_date(str(item["starts_at"]))
            item["can_open_attendance"] = (
                item["status"] in ATTENDANCE_OPEN_STATUSES
                and item["attendance_session_id"] is None
            )
            item["attendance_state"] = (
                "cancelled"
                if item["status"] in ATTENDANCE_LOCKED_STATUSES
                else "finalized"
                if item["attendance_session_id"] and item["is_finalized"]
                else "open"
                if item["attendance_session_id"]
                else "not_created"
            )
            result.append(item)
        return result

    def list_countdown_targets(
        self,
        team_ids: Iterable[int],
        *,
        season_id: int | None = None,
        season_label: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.supports_countdown_targets():
            return []
        allowed = _ids(team_ids)
        if not allowed:
            return []
        parameters: list[Any] = [*allowed]
        season_clause = ""
        if season_id is not None:
            season_clause = " AND e.season_id=?"
            parameters.append(int(season_id))
        elif season_label:
            season_clause = " AND s.label=?"
            parameters.append(season_label)
        rows = self.connection.execute(
            f"""SELECT e.id,e.team_id,e.season_id,e.event_type,e.status,e.starts_at,e.ends_at,
                       e.title,e.location,e.notes,s.label AS season_label,t.display_name AS team_name
                FROM calendar_events e
                JOIN seasons s ON s.id=e.season_id AND s.team_id=e.team_id
                JOIN teams t ON t.id=e.team_id
                WHERE e.team_id IN ({_placeholders(allowed)})
                  AND e.is_countdown_target=1
                  AND e.status IN('PLANNED','CONFIRMED')
                  {season_clause}
                ORDER BY e.starts_at,e.id""",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_training_event_for_session(
        self,
        session_id: int,
        team_ids: Iterable[int],
    ) -> dict[str, Any] | None:
        for event in self.list_training_events(team_ids):
            if event["attendance_session_id"] == int(session_id):
                return event
        return None

    def active_training_event(
        self,
        team_ids: Iterable[int],
        *,
        player_visible_only: bool = False,
    ) -> dict[str, Any] | None:
        candidates = [
            event
            for event in self.list_training_events(
                team_ids,
                player_visible_only=player_visible_only,
            )
            if event["status"] in ATTENDANCE_OPEN_STATUSES
            and (event["attendance_session_id"] is None or not bool(event["is_finalized"]))
        ]
        now = datetime.now(UTC)
        upcoming = next(
            (
                event
                for event in candidates
                if datetime.fromisoformat(str(event["ends_at"])).astimezone(UTC) >= now
            ),
            None,
        )
        return upcoming or (candidates[0] if candidates else None)

    def own_justification(
        self, event_id: int, *, player_member_id: int
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """SELECT id,event_id,player_member_id,reason,created_at,updated_at
               FROM calendar_justifications WHERE event_id=? AND player_member_id=?""",
            (int(event_id), int(player_member_id)),
        ).fetchone()
        return dict(row) if row else None

    def delete_own_justification(
        self,
        event_id: int,
        *,
        player_member_id: int,
        user_id: int,
        team_ids: Iterable[int],
    ) -> None:
        self._owned_justifiable_event(
            event_id, player_member_id=player_member_id, user_id=user_id, team_ids=team_ids
        )
        before = self.own_justification(event_id, player_member_id=player_member_id)
        if before is None:
            return
        self.connection.execute("DELETE FROM calendar_justifications WHERE id=?", (int(before["id"]),))
        self._audit(
            actor_user_id=user_id, action="calendar.justification.delete", entity="calendar_justification",
            target_id=int(before["id"]), before=before, after=None,
        )

    def get_or_create_attendance_session(
        self,
        event_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        event = self.get_event(event_id, team_ids)
        if event is None:
            raise KeyError("Treino não encontrado na equipe autorizada.")
        if event["event_type"] != "TRAINING":
            raise ValueError("Somente um treino pode abrir chamada de presença.")
        if event["status"] not in ATTENDANCE_OPEN_STATUSES:
            raise ValueError("Treino cancelado, remarcado ou concluído não pode abrir nova chamada.")
        session_id = event.get("attendance_session_id")
        if session_id is not None:
            session = self.connection.execute(
                "SELECT * FROM training_sessions WHERE id=?", (int(session_id),)
            ).fetchone()
            if session is None:
                raise RuntimeError("O vínculo de presença do treino está inválido.")
            return {"event": event, "session": dict(session), "created": False}

        training_date = _local_date(str(event["starts_at"]))
        legacy = self.connection.execute(
            """SELECT ts.* FROM training_sessions ts
               LEFT JOIN calendar_events ce ON ce.attendance_session_id=ts.id
               WHERE ts.training_date=? AND ce.id IS NULL
               ORDER BY ts.id""",
            (training_date,),
        ).fetchall()
        if len(legacy) > 1:
            raise ValueError(
                "Há chamadas históricas ambíguas nesta data; vincule-as antes de abrir o treino."
            )
        if legacy:
            unlinked_training_starts = self.connection.execute(
                """SELECT starts_at FROM calendar_events
                   WHERE event_type='TRAINING' AND attendance_session_id IS NULL"""
            ).fetchall()
            same_date_events = sum(
                _local_date(str(row["starts_at"])) == training_date
                for row in unlinked_training_starts
            )
            if same_date_events > 1:
                raise ValueError(
                    "Há mais de um treino sem chamada nesta data; vincule a "
                    "chamada histórica ao evento correto antes de continuar."
                )
        now = _now_iso()
        created = not legacy
        if legacy:
            session = dict(legacy[0])
        else:
            cursor = self.connection.execute(
                """INSERT INTO training_sessions(
                       training_date,notes,is_finalized,created_at,updated_at
                   ) VALUES(?, '', 0, ?, ?)""",
                (training_date, now, now),
            )
            session_id = int(cursor.lastrowid)
            self.connection.executemany(
                """INSERT INTO attendance_records(
                       session_id,member_id,confirmation_status,present,notes,updated_at
                   ) VALUES(?,?,'PENDING',NULL,'',?)""",
                [
                    (session_id, int(row["id"]), now)
                    for row in self.connection.execute(
                        "SELECT id FROM team_members WHERE active=1 ORDER BY name"
                    ).fetchall()
                ],
            )
            session = dict(
                self.connection.execute(
                    "SELECT * FROM training_sessions WHERE id=?", (session_id,)
                ).fetchone()
            )
        try:
            self.connection.execute(
                """UPDATE calendar_events
                   SET attendance_session_id=?,updated_by_user_id=?,updated_at=?
                   WHERE id=? AND attendance_session_id IS NULL""",
                (int(session["id"]), actor_user_id, now, int(event_id)),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("A chamada já está vinculada a outro treino.") from exc
        linked = self.get_event(event_id, team_ids)
        if linked is None or linked["attendance_session_id"] != int(session["id"]):
            raise RuntimeError("Não foi possível vincular a chamada ao treino.")
        self._audit(
            actor_user_id=actor_user_id,
            action="calendar.attendance.link",
            entity="calendar_event",
            target_id=int(event_id),
            before=event,
            after=linked,
        )
        return {"event": linked, "session": session, "created": created}

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
        if payload.get("opponent") and event_type is not CalendarEventType.GAME:
            raise ValueError("Adversário só se aplica a jogos.")
        if bool(payload.get("is_countdown_target")) and event_type is not CalendarEventType.CHAMPIONSHIP:
            raise ValueError("O alvo da contagem deve ser um campeonato.")
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

    def _record_transition(
        self,
        *,
        event_id: int,
        action: str,
        from_status: str | None,
        to_status: str,
        actor_user_id: int,
        reason: str = "",
        replacement_event_id: int | None = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
    ) -> None:
        if not self._table_exists("calendar_event_transitions"):
            return
        self.connection.execute(
            """INSERT INTO calendar_event_transitions(
                   event_id,action,from_status,to_status,reason,
                   replacement_event_id,actor_user_id,occurred_at,
                   before_json,after_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                int(event_id),
                action,
                from_status,
                to_status,
                reason.strip(),
                replacement_event_id,
                actor_user_id,
                _now_iso(),
                json.dumps(dict(before), ensure_ascii=False, sort_keys=True)
                if before is not None
                else None,
                json.dumps(dict(after), ensure_ascii=False, sort_keys=True)
                if after is not None
                else None,
            ),
        )

    def _assert_base_version(
        self,
        event: Mapping[str, Any],
        base_version: int | None,
    ) -> None:
        if base_version is None or not self.supports_professional_calendar():
            return
        if int(event["version"]) != int(base_version):
            raise CalendarProblem(
                code="calendar.stale_event",
                title="Este evento mudou em outro lugar",
                message="A versão que você abriu não é mais a versão atual.",
                suggestion="Recarregue o evento, confira as mudanças e tente novamente.",
                status_code=409,
            )

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
            if self.supports_professional_calendar() and self.supports_player_visibility():
                cursor = self.connection.execute(
                    """INSERT INTO calendar_events(
                           team_id,season_id,event_type,status,starts_at,ends_at,
                           location,notes,restriction_kind,attendance_session_id,
                           created_by_user_id,updated_by_user_id,created_at,updated_at,
                           title,opponent,all_day,version,series_id,is_countdown_target,
                           is_player_visible
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)""",
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
                        str(payload.get("title") or ""),
                        str(payload.get("opponent") or ""),
                        int(bool(payload.get("all_day"))),
                        payload.get("series_id"),
                        int(bool(payload.get("is_countdown_target"))),
                        int(bool(payload.get("is_player_visible"))),
                    ),
                )
            elif self.supports_professional_calendar():
                cursor = self.connection.execute(
                    """INSERT INTO calendar_events(
                           team_id,season_id,event_type,status,starts_at,ends_at,
                           location,notes,restriction_kind,attendance_session_id,
                           created_by_user_id,updated_by_user_id,created_at,updated_at,
                           title,opponent,all_day,version,series_id,is_countdown_target
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
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
                        str(payload.get("title") or ""),
                        str(payload.get("opponent") or ""),
                        int(bool(payload.get("all_day"))),
                        payload.get("series_id"),
                        int(bool(payload.get("is_countdown_target"))),
                    ),
                )
            else:
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
        self._record_transition(
            event_id=event_id,
            action="CREATE",
            from_status=None,
            to_status=str(event["status"]),
            actor_user_id=actor_user_id,
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
        self._assert_base_version(before, payload.get("version"))
        self._validate_event_payload(payload)
        if (
            before["attendance_session_id"] is not None
            and _local_date(str(before["starts_at"]))
            != _local_date(str(payload["starts_at"]))
        ):
            raise ValueError(
                "Um treino com chamada vinculada não pode mudar de dia; cancele/remarque e crie um novo treino."
            )
        visibility_value = (
            int(bool(before.get("is_player_visible")))
            if payload.get("is_player_visible") is None
            else int(bool(payload.get("is_player_visible")))
        )
        try:
            if self.supports_professional_calendar() and self.supports_player_visibility():
                self.connection.execute(
                    """UPDATE calendar_events
                       SET team_id=?,season_id=?,event_type=?,status=?,starts_at=?,
                           ends_at=?,location=?,notes=?,restriction_kind=?,
                           attendance_session_id=?,updated_by_user_id=?,updated_at=?,
                           title=?,opponent=?,all_day=?,is_countdown_target=?,
                           is_player_visible=?,version=version+1
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
                        str(payload.get("title") or ""),
                        str(payload.get("opponent") or ""),
                        int(bool(payload.get("all_day"))),
                        int(bool(payload.get("is_countdown_target"))),
                        visibility_value,
                        int(event_id),
                    ),
                )
            elif self.supports_professional_calendar():
                self.connection.execute(
                    """UPDATE calendar_events
                       SET team_id=?,season_id=?,event_type=?,status=?,starts_at=?,
                           ends_at=?,location=?,notes=?,restriction_kind=?,
                           attendance_session_id=?,updated_by_user_id=?,updated_at=?,
                           title=?,opponent=?,all_day=?,is_countdown_target=?,version=version+1
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
                        str(payload.get("title") or ""),
                        str(payload.get("opponent") or ""),
                        int(bool(payload.get("all_day"))),
                        int(bool(payload.get("is_countdown_target"))),
                        int(event_id),
                    ),
                )
            else:
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
        self._record_transition(
            event_id=event_id,
            action="UPDATE",
            from_status=str(before["status"]),
            to_status=str(after["status"]),
            actor_user_id=actor_user_id,
            before=before,
            after=after,
        )
        return after

    def check_conflicts(
        self,
        team_ids: Iterable[int],
        *,
        team_id: int,
        starts_at: str,
        ends_at: str,
        event_id: int | None = None,
    ) -> list[dict[str, Any]]:
        allowed = _ids(team_ids)
        if int(team_id) not in allowed:
            raise PermissionError("Equipe fora do escopo da conta.")
        parameters: list[Any] = [int(team_id), ends_at, starts_at]
        exclusion = ""
        if event_id is not None:
            exclusion = " AND e.id<>?"
            parameters.append(int(event_id))
        professional_projection = self._professional_projection()
        rows = self.connection.execute(
            f"""SELECT e.id,e.team_id,e.season_id,e.event_type,e.status,
                       e.starts_at,e.ends_at,e.location,e.notes,e.restriction_kind,
                       e.attendance_session_id,e.created_at,e.updated_at,
                       {professional_projection}
                       s.label season_label,t.display_name team_name,
                       ts.training_date attendance_training_date
                FROM calendar_events e
                JOIN seasons s ON s.id=e.season_id AND s.team_id=e.team_id
                JOIN teams t ON t.id=e.team_id
                LEFT JOIN training_sessions ts ON ts.id=e.attendance_session_id
                WHERE e.team_id=?
                  AND e.status NOT IN('CANCELLED','RESCHEDULED')
                  AND e.starts_at<? AND e.ends_at>?
                  {exclusion}
                ORDER BY e.starts_at,e.id""",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def set_player_visibility(
        self,
        event_id: int,
        *,
        is_player_visible: bool,
        team_ids: Iterable[int],
        actor_user_id: int,
        base_version: int | None = None,
    ) -> dict[str, Any]:
        """Altera somente a publicação do evento para atletas, com auditoria."""

        if not self.supports_player_visibility():
            raise CalendarProblem(
                code="calendar.upgrade_required",
                title="Atualização do calendário necessária",
                message="A publicação de eventos para atletas depende da migração V10.",
                suggestion="Aplique a migração controlada antes de usar esta opção.",
                status_code=409,
            )
        before = self.get_event(event_id, team_ids)
        if before is None:
            raise KeyError("Evento não encontrado na equipe autorizada.")
        self._assert_base_version(before, base_version)
        self.connection.execute(
            """UPDATE calendar_events
               SET is_player_visible=?,version=version+1,updated_by_user_id=?,updated_at=?
               WHERE id=?""",
            (int(bool(is_player_visible)), int(actor_user_id), _now_iso(), int(event_id)),
        )
        after = self.get_event(event_id, team_ids)
        if after is None:
            raise RuntimeError("Evento atualizado não pôde ser relido.")
        self._audit(
            actor_user_id=actor_user_id,
            action="calendar.event.set_player_visibility",
            entity="calendar_event",
            target_id=event_id,
            before=before,
            after=after,
        )
        return after

    def get_command_receipt(
        self,
        operation_id: str,
        *,
        actor_user_id: int,
        request_hash: str,
    ) -> dict[str, Any] | None:
        if not self._table_exists("calendar_command_receipts"):
            return None
        row = self.connection.execute(
            """SELECT request_hash,response_json FROM calendar_command_receipts
               WHERE operation_id=? AND actor_user_id=?""",
            (operation_id, actor_user_id),
        ).fetchone()
        if row is None:
            return None
        if str(row["request_hash"]) != request_hash:
            raise CalendarProblem(
                code="calendar.idempotency_conflict",
                title="Esta ação já foi usada",
                message="A mesma identificação de operação chegou com dados diferentes.",
                suggestion="Atualize a tela e tente novamente.",
                status_code=409,
            )
        return json.loads(str(row["response_json"]))

    def store_command_receipt(
        self,
        operation_id: str,
        *,
        actor_user_id: int,
        request_hash: str,
        response: Mapping[str, Any],
    ) -> None:
        if not self._table_exists("calendar_command_receipts"):
            return
        self.connection.execute(
            """INSERT INTO calendar_command_receipts(
                   operation_id,actor_user_id,request_hash,response_json,created_at
               ) VALUES(?,?,?,?,?)""",
            (
                operation_id,
                actor_user_id,
                request_hash,
                json.dumps(dict(response), ensure_ascii=False, sort_keys=True),
                _now_iso(),
            ),
        )

    def transition_event(
        self,
        event_id: int,
        *,
        action: str,
        team_ids: Iterable[int],
        actor_user_id: int,
        reason: str = "",
        base_version: int | None = None,
    ) -> dict[str, Any]:
        allowed = _ids(team_ids)
        before = self.get_event(event_id, allowed)
        if before is None:
            raise KeyError("Evento não encontrado na equipe autorizada.")
        if not self.supports_professional_calendar():
            raise CalendarProblem(
                code="calendar.upgrade_required",
                title="Atualização do calendário necessária",
                message="Esta ação ainda não está disponível no banco atual.",
                suggestion="Peça ao administrador para aplicar a atualização do Calendário.",
                status_code=409,
            )
        self._assert_base_version(before, base_version)
        current = str(before["status"])
        if action == "COMPLETE" and str(before["event_type"]) == "TRAINING":
            if before["attendance_session_id"] is None:
                raise CalendarProblem(
                    code="calendar.attendance_required",
                    title="Abra e encerre a chamada antes de concluir o treino",
                    message=(
                        "Todo treino precisa de uma chamada concluída antes do "
                        "fechamento, inclusive quando ninguém compareceu."
                    ),
                    suggestion="Abra a chamada do treino, registre as presenças e encerre-a.",
                    status_code=409,
                )
            session = self.connection.execute(
                "SELECT is_finalized FROM training_sessions WHERE id=?",
                (int(before["attendance_session_id"]),),
            ).fetchone()
            if session is None or not bool(session["is_finalized"]):
                raise CalendarProblem(
                    code="calendar.attendance_open",
                    title="Encerre a chamada antes de concluir o treino",
                    message=(
                        "Este treino possui uma chamada aberta. Confira as presenças "
                        "e encerre a chamada para apurar quem não respondeu."
                    ),
                    suggestion="Abra a chamada, registre a observação final e encerre-a.",
                    status_code=409,
                )
        transitions = {
            "CONFIRM": ({"PLANNED"}, "CONFIRMED"),
            "COMPLETE": ({"PLANNED", "CONFIRMED"}, "COMPLETED"),
            "CANCEL": ({"PLANNED", "CONFIRMED"}, "CANCELLED"),
        }
        if action == "UNDO_CANCEL":
            if current != "CANCELLED":
                raise CalendarProblem(
                    code="calendar.invalid_transition",
                    title="Este evento não está cancelado",
                    message="Só é possível desfazer um cancelamento ativo.",
                    suggestion="Recarregue o calendário para conferir o estado atual.",
                    status_code=409,
                )
            row = self.connection.execute(
                """SELECT from_status FROM calendar_event_transitions
                   WHERE event_id=? AND action='CANCEL'
                   ORDER BY id DESC LIMIT 1""",
                (int(event_id),),
            ).fetchone()
            target = (
                str(row["from_status"])
                if row is not None and row["from_status"] in {"PLANNED", "CONFIRMED"}
                else "PLANNED"
            )
        else:
            allowed_from, target = transitions[action]
            if current not in allowed_from:
                raise CalendarProblem(
                    code="calendar.invalid_transition",
                    title="Ação indisponível para este evento",
                    message=f"O evento está como {current.lower()} e não aceita esta ação.",
                    suggestion="Recarregue a tela e use uma das ações disponíveis.",
                    status_code=409,
                )
            if action == "CANCEL" and not reason.strip():
                raise CalendarProblem(
                    code="calendar.cancel_reason_required",
                    title="Informe o motivo do cancelamento",
                    message="O motivo ajuda a equipe a entender o que mudou.",
                    suggestion="Escreva uma frase curta e confirme novamente.",
                    field="reason",
                )
        now = _now_iso()
        self.connection.execute(
            """UPDATE calendar_events
               SET status=?,is_countdown_target=CASE WHEN ?='CANCEL' THEN 0 ELSE is_countdown_target END,
                   version=version+1,updated_by_user_id=?,updated_at=?
               WHERE id=?""",
            (target, action, actor_user_id, now, int(event_id)),
        )
        after = self.get_event(event_id, allowed)
        if after is None:
            raise RuntimeError("Evento atualizado não pôde ser relido.")
        self._record_transition(
            event_id=event_id,
            action=action,
            from_status=current,
            to_status=target,
            actor_user_id=actor_user_id,
            reason=reason,
            before=before,
            after=after,
        )
        self._audit(
            actor_user_id=actor_user_id,
            action=f"calendar.event.{action.casefold()}",
            entity="calendar_event",
            target_id=event_id,
            before=before,
            after=after,
        )
        return after

    def reschedule_event(
        self,
        event_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        starts_at: str,
        ends_at: str,
        reason: str,
        base_version: int | None = None,
    ) -> dict[str, Any]:
        allowed = _ids(team_ids)
        before = self.get_event(event_id, allowed)
        if before is None:
            raise KeyError("Evento não encontrado na equipe autorizada.")
        if not self.supports_professional_calendar():
            raise CalendarProblem(
                code="calendar.upgrade_required",
                title="Atualização do calendário necessária",
                message="A remarcação guiada depende da atualização do Calendário.",
                suggestion="Peça ao administrador para aplicar a atualização pendente.",
                status_code=409,
            )
        self._assert_base_version(before, base_version)
        if str(before["status"]) not in {"PLANNED", "CONFIRMED"}:
            raise CalendarProblem(
                code="calendar.invalid_transition",
                title="Este evento não pode ser remarcado",
                message="Somente eventos planejados ou confirmados podem ser remarcados.",
                suggestion="Recarregue a tela e confira o estado atual.",
                status_code=409,
            )
        replacement_payload = {
            **before,
            "status": "PLANNED",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "attendance_session_id": None,
            "version": None,
            "series_id": None,
        }
        if bool(before.get("is_countdown_target")):
            self.connection.execute(
                "UPDATE calendar_events SET is_countdown_target=0 WHERE id=?",
                (int(event_id),),
            )
        replacement = self.create_event(
            replacement_payload,
            actor_user_id=actor_user_id,
        )
        now = _now_iso()
        self.connection.execute(
            """UPDATE calendar_events
               SET status='RESCHEDULED',version=version+1,
                   updated_by_user_id=?,updated_at=?
               WHERE id=?""",
            (actor_user_id, now, int(event_id)),
        )
        after = self.get_event(event_id, allowed)
        if after is None:
            raise RuntimeError("Evento remarcado não pôde ser relido.")
        self._record_transition(
            event_id=event_id,
            action="RESCHEDULE",
            from_status=str(before["status"]),
            to_status="RESCHEDULED",
            actor_user_id=actor_user_id,
            reason=reason,
            replacement_event_id=int(replacement["id"]),
            before=before,
            after=after,
        )
        self._audit(
            actor_user_id=actor_user_id,
            action="calendar.event.reschedule",
            entity="calendar_event",
            target_id=event_id,
            before=before,
            after={"event": after, "replacement": replacement},
        )
        return {"event": after, "replacement": replacement}

    def event_history(
        self,
        event_id: int,
        *,
        team_ids: Iterable[int],
        player_visible_only: bool = False,
    ) -> list[dict[str, Any]]:
        if self.get_event(
            event_id,
            team_ids,
            player_visible_only=player_visible_only,
        ) is None:
            raise KeyError("Evento não encontrado na equipe autorizada.")
        if not self._table_exists("calendar_event_transitions"):
            return []
        rows = self.connection.execute(
            """SELECT id,event_id,action,from_status,to_status,reason,
                      replacement_event_id,actor_user_id,occurred_at
               FROM calendar_event_transitions
               WHERE event_id=? ORDER BY occurred_at,id""",
            (int(event_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def create_series(
        self,
        payload: Mapping[str, Any],
        occurrences: Iterable[Mapping[str, Any]],
        *,
        actor_user_id: int,
    ) -> dict[str, Any]:
        if not self.supports_professional_calendar():
            raise CalendarProblem(
                code="calendar.upgrade_required",
                title="Atualização do calendário necessária",
                message="Séries recorrentes ainda não estão disponíveis no banco atual.",
                suggestion="Peça ao administrador para aplicar a atualização pendente.",
                status_code=409,
            )
        occurrence_items = [dict(item) for item in occurrences]
        for occurrence in occurrence_items:
            conflicts = self.check_conflicts(
                (int(payload["team_id"]),),
                team_id=int(payload["team_id"]),
                starts_at=str(occurrence["starts_at"]),
                ends_at=str(occurrence["ends_at"]),
            )
            if conflicts:
                raise CalendarProblem(
                    code="calendar.series_conflict",
                    title="A série possui conflitos",
                    message="Um ou mais horários coincidem com eventos existentes.",
                    suggestion="Revise a prévia e ajuste os dias ou horários.",
                    status_code=409,
                )
        now = _now_iso()
        cursor = self.connection.execute(
            """INSERT INTO calendar_event_series(
                   team_id,season_id,event_type,title,opponent,starts_on,ends_on,
                   start_time,duration_minutes,weekdays_json,location,notes,
                   restriction_kind,created_by_user_id,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(payload["team_id"]),
                int(payload["season_id"]),
                str(payload["event_type"]),
                str(payload.get("title") or ""),
                str(payload.get("opponent") or ""),
                str(payload["starts_on"]),
                str(payload["ends_on"]),
                str(payload["start_time"]),
                int(payload["duration_minutes"]),
                json.dumps(list(payload["weekdays"])),
                str(payload.get("location") or ""),
                str(payload.get("notes") or ""),
                payload.get("restriction_kind"),
                actor_user_id,
                now,
                now,
            ),
        )
        series_id = int(cursor.lastrowid)
        events: list[dict[str, Any]] = []
        for occurrence in occurrence_items:
            event = self.create_event(
                {**occurrence, "series_id": series_id},
                actor_user_id=actor_user_id,
            )
            events.append(event)
            self._record_transition(
                event_id=int(event["id"]),
                action="SERIES_CREATE",
                from_status=None,
                to_status=str(event["status"]),
                actor_user_id=actor_user_id,
                after=event,
            )
        return {"series_id": series_id, "count": len(events), "items": events}

    def update_series(
        self,
        series_id: int,
        payload: Mapping[str, Any],
        *,
        scope: str,
        anchor_event_id: int,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        if not self.supports_professional_calendar():
            raise CalendarProblem(
                code="calendar.upgrade_required",
                title="Atualização do calendário necessária",
                message="A edição de séries depende da atualização do Calendário.",
                suggestion="Peça ao administrador para aplicar a atualização pendente.",
                status_code=409,
            )
        if scope not in {"FUTURE", "ALL"}:
            raise CalendarProblem(
                code="calendar.invalid_series_scope",
                title="Escopo de edição inválido",
                message="A edição deve afetar os próximos eventos ou a série inteira.",
                suggestion="Escolha uma das opções exibidas e tente novamente.",
            )
        allowed = _ids(team_ids)
        anchor = self.get_event(anchor_event_id, allowed)
        if anchor is None or int(anchor.get("series_id") or 0) != int(series_id):
            raise KeyError("Ocorrência da série não encontrada na equipe autorizada.")
        self._assert_base_version(anchor, payload.get("version"))
        if (
            int(payload["team_id"]) != int(anchor["team_id"])
            or int(payload["season_id"]) != int(anchor["season_id"])
        ):
            raise CalendarProblem(
                code="calendar.series_context_locked",
                title="Equipe e temporada não podem mudar em lote",
                message="Uma série permanece na equipe e temporada em que foi criada.",
                suggestion="Edite apenas esta ocorrência ou crie uma nova série.",
            )
        submitted_start = datetime.fromisoformat(str(payload["starts_at"]))
        submitted_end = datetime.fromisoformat(str(payload["ends_at"]))
        anchor_start = datetime.fromisoformat(str(anchor["starts_at"]))
        if _local_date(str(payload["starts_at"])) != _local_date(
            str(anchor["starts_at"])
        ):
            raise CalendarProblem(
                code="calendar.series_date_shift",
                title="A data só pode mudar em uma ocorrência",
                message="Edições em lote mantêm os mesmos dias e ajustam horário e conteúdo.",
                suggestion="Escolha “Só este evento” para mudar a data.",
                field="starts_at",
            )
        time_shift = submitted_start - anchor_start
        duration = submitted_end - submitted_start
        placeholders = _placeholders(allowed)
        scope_clause = "AND starts_at>=?" if scope == "FUTURE" else ""
        parameters: list[Any] = [int(series_id), *allowed]
        if scope == "FUTURE":
            parameters.append(str(anchor["starts_at"]))
        rows = self.connection.execute(
            f"""SELECT id FROM calendar_events
                WHERE series_id=? AND team_id IN ({placeholders})
                  AND status IN('PLANNED','CONFIRMED') {scope_clause}
                ORDER BY starts_at,id""",
            parameters,
        ).fetchall()
        planned: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for row in rows:
            current = self.get_event(int(row["id"]), allowed)
            if current is None:
                continue
            current_start = datetime.fromisoformat(str(current["starts_at"]))
            next_start = current_start + time_shift
            next_end = next_start + duration
            item_payload = {
                **current,
                "event_type": str(payload["event_type"]),
                "status": str(current["status"]),
                "starts_at": next_start.isoformat(timespec="seconds"),
                "ends_at": next_end.isoformat(timespec="seconds"),
                "location": str(payload.get("location") or ""),
                "notes": str(payload.get("notes") or ""),
                "title": str(payload.get("title") or ""),
                "opponent": str(payload.get("opponent") or ""),
                "all_day": bool(payload.get("all_day")),
                "restriction_kind": payload.get("restriction_kind"),
                "attendance_session_id": current.get("attendance_session_id"),
                "version": current.get("version"),
            }
            conflicts = self.check_conflicts(
                allowed,
                team_id=int(current["team_id"]),
                starts_at=str(item_payload["starts_at"]),
                ends_at=str(item_payload["ends_at"]),
                event_id=int(current["id"]),
            )
            if conflicts:
                raise CalendarProblem(
                    code="calendar.series_conflict",
                    title="A edição da série possui conflitos",
                    message=(
                        "O novo horário de uma ou mais ocorrências coincide "
                        "com outro evento."
                    ),
                    suggestion=(
                        "Ajuste o horário ou escolha “Só este evento” para "
                        "fazer uma alteração pontual."
                    ),
                    status_code=409,
                )
            planned.append((current, item_payload))
        if not planned:
            raise CalendarProblem(
                code="calendar.empty_series_scope",
                title="Nenhum evento ativo para editar",
                message="O recorte escolhido não possui eventos planejados ou confirmados.",
                suggestion="Confira o evento selecionado ou edite apenas esta ocorrência.",
                status_code=409,
            )
        updated: list[dict[str, Any]] = []
        for current, item_payload in planned:
            updated.append(
                self.update_event(
                    int(current["id"]),
                    item_payload,
                    actor_user_id=actor_user_id,
                )
            )
        local_start = submitted_start.astimezone(LOCAL_TIMEZONE)
        self.connection.execute(
            """UPDATE calendar_event_series
               SET event_type=?,title=?,opponent=?,start_time=?,
                   duration_minutes=?,location=?,notes=?,restriction_kind=?,
                   updated_at=?
               WHERE id=? AND team_id=?""",
            (
                str(payload["event_type"]),
                str(payload.get("title") or ""),
                str(payload.get("opponent") or ""),
                local_start.time().isoformat(timespec="minutes"),
                max(1, int(duration.total_seconds() // 60)),
                str(payload.get("location") or ""),
                str(payload.get("notes") or ""),
                payload.get("restriction_kind"),
                _now_iso(),
                int(series_id),
                int(anchor["team_id"]),
            ),
        )
        self._audit(
            actor_user_id=actor_user_id,
            action="calendar.series.update",
            entity="calendar_event_series",
            target_id=series_id,
            before={"scope": scope, "anchor_event_id": anchor_event_id},
            after={"updated_event_ids": [int(item["id"]) for item in updated]},
        )
        return {
            "series_id": int(series_id),
            "scope": scope,
            "count": len(updated),
            "items": updated,
        }

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
        visibility_clause = (
            " AND e.is_player_visible=1"
            if self.supports_player_visibility()
            else ""
        )
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
                WHERE e.id=? AND e.team_id IN ({placeholders}){visibility_clause}""",
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
