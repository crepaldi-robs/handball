from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import uuid4

from .shared import LOCAL_TIMEZONE, now_iso


PUBLISHED_EVENT_TYPES = frozenset({"TRAINING", "GAME", "CHAMPIONSHIP"})
CONNECTION_STATUSES = frozenset(
    {"CONNECTED", "PAUSED", "REAUTH_REQUIRED", "DISCONNECTED"}
)


class IntegrationRepository:
    """SQL da integração Google, sempre limitado pelo ``team_id``."""

    def __init__(self, connection: Any, *, read_only: bool = False) -> None:
        self.connection = connection
        self._read_only = bool(read_only)

    def _require_write(self) -> None:
        if self._read_only:
            raise RuntimeError("Repositório de integrações está somente leitura.")

    def is_available(self) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='google_connections'"
        ).fetchone()
        return row is not None

    def _require_available(self) -> None:
        if not self.is_available():
            raise RuntimeError("A integração Google aguarda a migration do banco.")

    @staticmethod
    def _as_status(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["is_public"] = bool(result.get("is_public"))
        result["auto_sync"] = bool(result.get("auto_sync"))
        result["publish_trainings"] = bool(result.get("publish_trainings"))
        result["publish_games"] = bool(result.get("publish_games"))
        result["publish_championships"] = bool(
            result.get("publish_championships")
        )
        result["pending_operations"] = int(result.get("pending_operations") or 0)
        result["failed_operations"] = int(result.get("failed_operations") or 0)
        try:
            result["granted_scopes"] = json.loads(
                str(result.pop("granted_scopes_json", "[]"))
            )
        except json.JSONDecodeError:
            result["granted_scopes"] = []
        return result

    def status(self, team_id: int) -> dict[str, Any] | None:
        self._require_available()
        row = self.connection.execute(
            """SELECT c.*,s.calendar_id,s.calendar_name,s.public_url,s.is_public,
                      s.auto_sync,s.publish_trainings,s.publish_games,
                      s.publish_championships,s.last_sync_at,s.last_sync_status,
                      s.last_error_code,s.last_error_message,
                      (SELECT COUNT(*) FROM integration_outbox o
                       WHERE o.team_id=c.team_id AND o.provider='GOOGLE'
                         AND o.status IN('PENDING','PROCESSING')) pending_operations,
                      (SELECT COUNT(*) FROM integration_outbox o
                       WHERE o.team_id=c.team_id AND o.provider='GOOGLE'
                         AND o.status='FAILED') failed_operations
               FROM google_connections c
               LEFT JOIN google_calendar_settings s ON s.connection_id=c.id
               WHERE c.team_id=?""",
            (int(team_id),),
        ).fetchone()
        return self._as_status(row) if row is not None else None

    def _audit(
        self,
        *,
        actor_user_id: int,
        action: str,
        team_id: int,
        before: Any = None,
        after: Any = None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO security_audit_events(
                   actor_user_id,occurred_at,action,entity,target_id,origin,
                   before_json,after_json,request_id
               ) VALUES(?,?,?,?,?,'google-integration',?,?,NULL)""",
            (
                int(actor_user_id),
                now_iso(),
                action,
                "team_google_connection",
                str(int(team_id)),
                json.dumps(before, ensure_ascii=False, sort_keys=True)
                if before is not None
                else None,
                json.dumps(after, ensure_ascii=False, sort_keys=True)
                if after is not None
                else None,
            ),
        )

    def upsert_connection(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._require_write()
        self._require_available()
        team_id = int(payload["team_id"])
        actor_user_id = int(payload["connected_by_user_id"])
        before = self.status(team_id)
        old_subject = str(before.get("google_subject") or "") if before else ""
        new_subject = str(payload["google_subject"])
        if before and old_subject != new_subject:
            self.connection.execute(
                "DELETE FROM google_calendar_event_links WHERE connection_id=?",
                (int(before["id"]),),
            )
            self.connection.execute(
                "DELETE FROM google_calendar_settings WHERE connection_id=?",
                (int(before["id"]),),
            )
        now = now_iso()
        self.connection.execute(
            """INSERT INTO google_connections(
                   team_id,connection_uuid,google_subject,account_email,
                   granted_scopes_json,credential_ref,status,version,
                   connected_by_user_id,connected_at,last_verified_at,
                   disconnected_at,updated_at
               ) VALUES(?,?,?,?,?,?,'CONNECTED',1,?,?,?,NULL,?)
               ON CONFLICT(team_id) DO UPDATE SET
                   connection_uuid=excluded.connection_uuid,
                   google_subject=excluded.google_subject,
                   account_email=excluded.account_email,
                   granted_scopes_json=excluded.granted_scopes_json,
                   credential_ref=excluded.credential_ref,
                   status='CONNECTED',version=google_connections.version+1,
                   connected_by_user_id=excluded.connected_by_user_id,
                   connected_at=excluded.connected_at,
                   last_verified_at=excluded.last_verified_at,
                   disconnected_at=NULL,updated_at=excluded.updated_at""",
            (
                team_id,
                str(payload.get("connection_uuid") or uuid4()),
                new_subject,
                str(payload["account_email"]).strip().casefold(),
                json.dumps(
                    sorted({str(value) for value in payload.get("granted_scopes", ())}),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                str(payload["credential_ref"]),
                actor_user_id,
                now,
                now,
                now,
            ),
        )
        after = self.status(team_id)
        self._audit(
            actor_user_id=actor_user_id,
            action="google.connection.upsert",
            team_id=team_id,
            before={"account_email": before.get("account_email"), "status": before.get("status")} if before else None,
            after={"account_email": after.get("account_email"), "status": after.get("status")} if after else None,
        )
        if after is None:
            raise RuntimeError("A conexão Google não pôde ser persistida.")
        return after

    def save_calendar(
        self,
        team_id: int,
        payload: Mapping[str, Any],
        *,
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_write()
        connection = self.status(team_id)
        if connection is None:
            raise ValueError("O time ainda não conectou uma conta Google.")
        now = now_iso()
        self.connection.execute(
            """INSERT INTO google_calendar_settings(
                   connection_id,calendar_id,calendar_name,public_url,is_public,
                   auto_sync,publish_trainings,publish_games,publish_championships,
                   last_sync_status,updated_by_user_id,updated_at
               ) VALUES(?,?,?,?,?,1,1,1,1,'PENDING',?,?)
               ON CONFLICT(connection_id) DO UPDATE SET
                   calendar_id=excluded.calendar_id,
                   calendar_name=excluded.calendar_name,
                   public_url=excluded.public_url,
                   is_public=excluded.is_public,
                   last_sync_status='PENDING',last_error_code=NULL,
                   last_error_message=NULL,updated_by_user_id=excluded.updated_by_user_id,
                   updated_at=excluded.updated_at""",
            (
                int(connection["id"]),
                str(payload["calendar_id"]),
                str(payload["calendar_name"]),
                str(payload["public_url"]),
                1 if payload.get("is_public") else 0,
                int(actor_user_id),
                now,
            ),
        )
        self._audit(
            actor_user_id=actor_user_id,
            action="google.calendar.setup",
            team_id=team_id,
            after={"calendar_name": payload["calendar_name"], "is_public": bool(payload.get("is_public"))},
        )
        result = self.status(team_id)
        if result is None:
            raise RuntimeError("O calendário Google não pôde ser persistido.")
        return result

    def update_settings(
        self,
        team_id: int,
        payload: Mapping[str, Any],
        *,
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_write()
        before = self.status(team_id)
        if before is None or not before.get("calendar_id"):
            raise ValueError("O calendário Google ainda não foi configurado.")
        updated = self.connection.execute(
            """UPDATE google_calendar_settings SET
                   publish_trainings=?,publish_games=?,publish_championships=?,
                   last_sync_status='PENDING',updated_by_user_id=?,updated_at=?
               WHERE connection_id=?""",
            (
                1 if payload.get("publish_trainings", True) else 0,
                1 if payload.get("publish_games", True) else 0,
                1 if payload.get("publish_championships", True) else 0,
                int(actor_user_id),
                now_iso(),
                int(before["id"]),
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("As configurações não puderam ser atualizadas.")
        after = self.status(team_id)
        self._audit(
            actor_user_id=actor_user_id,
            action="google.calendar.settings.update",
            team_id=team_id,
            before={key: before[key] for key in ("publish_trainings", "publish_games", "publish_championships")},
            after={key: after[key] for key in ("publish_trainings", "publish_games", "publish_championships")} if after else None,
        )
        return after or before

    def set_connection_status(
        self,
        team_id: int,
        status: str,
        *,
        actor_user_id: int,
        audit_action: str,
    ) -> dict[str, Any]:
        self._require_write()
        if status not in CONNECTION_STATUSES:
            raise ValueError("Estado de conexão Google inválido.")
        before = self.status(team_id)
        if before is None:
            raise ValueError("O time ainda não conectou uma conta Google.")
        self.connection.execute(
            """UPDATE google_connections SET status=?,version=version+1,
                      disconnected_at=CASE WHEN ?='DISCONNECTED' THEN ? ELSE NULL END,
                      updated_at=? WHERE team_id=?""",
            (status, status, now_iso(), now_iso(), int(team_id)),
        )
        after = self.status(team_id)
        self._audit(
            actor_user_id=actor_user_id,
            action=audit_action,
            team_id=team_id,
            before={"status": before["status"]},
            after={"status": status},
        )
        return after or before

    def _publishable(self, team_id: int, event_type: str) -> bool:
        status = self.status(team_id)
        if status is None or status["status"] == "DISCONNECTED" or not status.get("calendar_id"):
            return False
        flags = {
            "TRAINING": "publish_trainings",
            "GAME": "publish_games",
            "CHAMPIONSHIP": "publish_championships",
        }
        key = flags.get(event_type)
        return bool(key and status.get(key))

    def enqueue_event(self, event_id: int) -> str | None:
        self._require_write()
        event = self.connection.execute(
            """SELECT e.id,e.team_id,e.event_type,e.version,s.active season_active
               FROM calendar_events e JOIN seasons s ON s.id=e.season_id
               WHERE e.id=?""",
            (int(event_id),),
        ).fetchone()
        if event is None:
            return None
        if not bool(event["season_active"]) or not self._publishable(
            int(event["team_id"]), str(event["event_type"])
        ):
            return self.enqueue_delete_event(int(event["id"]))
        operation_id = f"google-calendar:{int(event['id'])}:v{int(event['version'])}"
        now = now_iso()
        self.connection.execute(
            """UPDATE integration_outbox SET status='SUCCEEDED',updated_at=?
               WHERE provider='GOOGLE' AND team_id=? AND aggregate_type='CALENDAR_EVENT'
                 AND aggregate_id=? AND action='DELETE_EVENT' AND status='PENDING'""",
            (now, int(event["team_id"]), int(event["id"])),
        )
        self.connection.execute(
            """INSERT INTO integration_outbox(
                   operation_id,provider,team_id,aggregate_type,aggregate_id,
                   action,desired_version,status,attempts,available_at,
                   created_at,updated_at
               ) VALUES(?,'GOOGLE',?,'CALENDAR_EVENT',?,'UPSERT_EVENT',?,
                        'PENDING',0,?,?,?)
               ON CONFLICT(operation_id) DO UPDATE SET
                   status='PENDING',attempts=0,available_at=excluded.available_at,
                   last_error_code=NULL,last_error_message=NULL,
                   updated_at=excluded.updated_at""",
            (
                operation_id,
                int(event["team_id"]),
                int(event["id"]),
                int(event["version"]),
                now,
                now,
                now,
            ),
        )
        return operation_id

    def enqueue_delete_event(self, event_id: int) -> str | None:
        self._require_write()
        row = self.connection.execute(
            """SELECT e.id,e.team_id,e.version,l.connection_id
               FROM calendar_events e
               JOIN google_calendar_event_links l ON l.calendar_event_id=e.id
               JOIN google_connections c ON c.id=l.connection_id AND c.team_id=e.team_id
               WHERE e.id=?""",
            (int(event_id),),
        ).fetchone()
        if row is None:
            return None
        now = now_iso()
        self.connection.execute(
            """UPDATE integration_outbox SET status='SUCCEEDED',updated_at=?
               WHERE provider='GOOGLE' AND team_id=? AND aggregate_type='CALENDAR_EVENT'
                 AND aggregate_id=? AND action='UPSERT_EVENT' AND status='PENDING'""",
            (now, int(row["team_id"]), int(row["id"])),
        )
        operation_id = (
            f"google-calendar:{int(row['id'])}:delete:v{int(row['version'])}"
        )
        self.connection.execute(
            """INSERT INTO integration_outbox(
                   operation_id,provider,team_id,aggregate_type,aggregate_id,
                   action,desired_version,status,attempts,available_at,
                   created_at,updated_at
               ) VALUES(?,'GOOGLE',?,'CALENDAR_EVENT',?,'DELETE_EVENT',?,
                        'PENDING',0,?,?,?)
               ON CONFLICT(operation_id) DO UPDATE SET
                   status='PENDING',attempts=0,available_at=excluded.available_at,
                   last_error_code=NULL,last_error_message=NULL,
                   updated_at=excluded.updated_at""",
            (
                operation_id,
                int(row["team_id"]),
                int(row["id"]),
                int(row["version"]),
                now,
                now,
                now,
            ),
        )
        return operation_id

    def enqueue_reconcile(self, team_id: int) -> str:
        self._require_write()
        now = now_iso()
        operation_id = f"google-calendar-reconcile:{int(team_id)}:{uuid4().hex}"
        self.connection.execute(
            """INSERT INTO integration_outbox(
                   operation_id,provider,team_id,aggregate_type,aggregate_id,
                   action,desired_version,status,attempts,available_at,
                   created_at,updated_at
               ) VALUES(?,'GOOGLE',?,'CALENDAR',?,'RECONCILE_CALENDAR',1,
                        'PENDING',0,?,?,?)""",
            (operation_id, int(team_id), int(team_id), now, now, now),
        )
        return operation_id

    def _event_select(self) -> str:
        return """SELECT e.id,e.team_id,e.season_id,e.event_type,e.status,
                         e.starts_at,e.ends_at,e.location,e.title,e.opponent,
                         e.all_day,e.version,t.display_name team_name
                  FROM calendar_events e JOIN teams t ON t.id=e.team_id"""

    def events_for_active_season(self, team_id: int) -> list[dict[str, Any]]:
        status = self.status(team_id)
        if status is None:
            return []
        enabled: list[str] = []
        if status.get("publish_trainings"):
            enabled.append("TRAINING")
        if status.get("publish_games"):
            enabled.append("GAME")
        if status.get("publish_championships"):
            enabled.append("CHAMPIONSHIP")
        if not enabled:
            return []
        placeholders = ",".join("?" for _ in enabled)
        rows = self.connection.execute(
            self._event_select()
            + f""" JOIN seasons s ON s.id=e.season_id AND s.team_id=e.team_id
                    WHERE e.team_id=? AND s.active=1
                      AND e.event_type IN ({placeholders})
                    ORDER BY e.starts_at,e.id""",
            (int(team_id), *enabled),
        ).fetchall()
        return [dict(row) for row in rows]

    def linked_events_outside_policy(self, team_id: int) -> list[dict[str, Any]]:
        status = self.status(team_id)
        if status is None:
            return []
        rows = self.connection.execute(
            """SELECT e.id,e.team_id,e.event_type,e.version,s.active season_active
               FROM google_calendar_event_links l
               JOIN google_connections c ON c.id=l.connection_id
               JOIN calendar_events e ON e.id=l.calendar_event_id
               JOIN seasons s ON s.id=e.season_id
               WHERE c.team_id=?""",
            (int(team_id),),
        ).fetchall()
        flags = {
            "TRAINING": bool(status.get("publish_trainings")),
            "GAME": bool(status.get("publish_games")),
            "CHAMPIONSHIP": bool(status.get("publish_championships")),
        }
        return [
            dict(row)
            for row in rows
            if not bool(row["season_active"])
            or not flags.get(str(row["event_type"]), False)
        ]

    def event_for_sync(self, team_id: int, event_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            self._event_select() + " WHERE e.team_id=? AND e.id=?",
            (int(team_id), int(event_id)),
        ).fetchone()
        return dict(row) if row is not None else None

    def claim_ready(self, team_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        self._require_write()
        now = now_iso()
        stale = (datetime.now(LOCAL_TIMEZONE) - timedelta(minutes=10)).isoformat(
            timespec="seconds"
        )
        self.connection.execute(
            """UPDATE integration_outbox SET status='PENDING',updated_at=?
               WHERE provider='GOOGLE' AND team_id=? AND status='PROCESSING'
                 AND updated_at<?""",
            (now, int(team_id), stale),
        )
        connection = self.status(team_id)
        if connection is None or connection["status"] != "CONNECTED":
            return []
        rows = self.connection.execute(
            """SELECT * FROM integration_outbox
               WHERE provider='GOOGLE' AND team_id=? AND status='PENDING'
                 AND available_at<=?
               ORDER BY created_at,operation_id LIMIT ?""",
            (int(team_id), now, max(1, min(int(limit), 200))),
        ).fetchall()
        claimed = [dict(row) for row in rows]
        self.connection.executemany(
            "UPDATE integration_outbox SET status='PROCESSING',updated_at=? WHERE operation_id=? AND status='PENDING'",
            [(now, row["operation_id"]) for row in claimed],
        )
        return claimed

    def mark_succeeded(self, operation_id: str) -> None:
        self._require_write()
        self.connection.execute(
            """UPDATE integration_outbox SET status='SUCCEEDED',
                      last_error_code=NULL,last_error_message=NULL,updated_at=?
               WHERE operation_id=?""",
            (now_iso(), operation_id),
        )

    def mark_failed(
        self,
        operation_id: str,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        self._require_write()
        row = self.connection.execute(
            "SELECT attempts FROM integration_outbox WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        attempts = int(row["attempts"] if row else 0) + 1
        delay_seconds = min(3600, 15 * (2 ** min(attempts - 1, 8)))
        available_at = (
            datetime.now(LOCAL_TIMEZONE) + timedelta(seconds=delay_seconds)
        ).isoformat(timespec="seconds")
        self.connection.execute(
            """UPDATE integration_outbox SET status=?,attempts=?,available_at=?,
                      last_error_code=?,last_error_message=?,updated_at=?
               WHERE operation_id=?""",
            (
                "PENDING" if retryable else "FAILED",
                attempts,
                available_at,
                str(code)[:120],
                str(message)[:500],
                now_iso(),
                operation_id,
            ),
        )

    def event_link(self, connection_id: int, event_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            """SELECT * FROM google_calendar_event_links
               WHERE connection_id=? AND calendar_event_id=?""",
            (int(connection_id), int(event_id)),
        ).fetchone()
        return dict(row) if row is not None else None

    def delete_event_link(self, connection_id: int, event_id: int) -> None:
        self._require_write()
        self.connection.execute(
            """DELETE FROM google_calendar_event_links
               WHERE connection_id=? AND calendar_event_id=?""",
            (int(connection_id), int(event_id)),
        )

    def upsert_event_link(self, payload: Mapping[str, Any]) -> None:
        self._require_write()
        self.connection.execute(
            """INSERT INTO google_calendar_event_links(
                   calendar_event_id,connection_id,google_event_id,google_etag,
                   last_local_version,last_synced_at
               ) VALUES(?,?,?,?,?,?)
               ON CONFLICT(calendar_event_id) DO UPDATE SET
                   connection_id=excluded.connection_id,
                   google_event_id=excluded.google_event_id,
                   google_etag=excluded.google_etag,
                   last_local_version=excluded.last_local_version,
                   last_synced_at=excluded.last_synced_at""",
            (
                int(payload["calendar_event_id"]),
                int(payload["connection_id"]),
                str(payload["google_event_id"]),
                str(payload.get("google_etag") or ""),
                int(payload["last_local_version"]),
                str(payload.get("last_synced_at") or now_iso()),
            ),
        )

    def record_sync_result(
        self,
        team_id: int,
        *,
        status: str,
        code: str | None = None,
        message: str | None = None,
    ) -> None:
        self._require_write()
        connection = self.status(team_id)
        if connection is None or not connection.get("calendar_id"):
            return
        self.connection.execute(
            """UPDATE google_calendar_settings SET last_sync_at=?,
                      last_sync_status=?,last_error_code=?,last_error_message=?,
                      updated_at=? WHERE connection_id=?""",
            (
                now_iso(),
                status,
                str(code)[:120] if code else None,
                str(message)[:500] if message else None,
                now_iso(),
                int(connection["id"]),
            ),
        )

    def disconnect(self, team_id: int, *, actor_user_id: int) -> dict[str, Any]:
        self._require_write()
        connection = self.status(team_id)
        if connection is None:
            raise ValueError("O time ainda não conectou uma conta Google.")
        if connection.get("calendar_id"):
            self.connection.execute(
                """UPDATE google_calendar_settings SET is_public=0,
                          last_sync_status='NEVER',last_error_code=NULL,
                          last_error_message=NULL,updated_by_user_id=?,updated_at=?
                   WHERE connection_id=?""",
                (int(actor_user_id), now_iso(), int(connection["id"])),
            )
        return self.set_connection_status(
            team_id,
            "DISCONNECTED",
            actor_user_id=actor_user_id,
            audit_action="google.connection.disconnect",
        )
