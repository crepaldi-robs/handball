from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import uuid4

from handball.core.authorization import AccessContext, Permission
from handball.core.config import AppSettings
from handball.database.contracts import UnitOfWorkFactoryContract
from handball.integrations.google import (
    GOOGLE_SCOPES,
    GoogleCalendarClient,
    GoogleIntegrationError,
    GoogleOAuthClient,
    TokenVault,
    pkce_challenge,
)


class GoogleIntegrationService:
    """Orquestra OAuth, calendário e outbox sem conhecer SQLite."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactoryContract,
        settings: AppSettings,
        token_vault: TokenVault,
        *,
        oauth_client: GoogleOAuthClient | None = None,
        calendar_client: GoogleCalendarClient | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._settings = settings
        self._token_vault = token_vault
        self._oauth = oauth_client or GoogleOAuthClient(
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            redirect_uri=settings.google_oauth_redirect_uri,
        )
        self._calendar = calendar_client or GoogleCalendarClient()
        self._sync_locks: dict[int, threading.Lock] = {}
        self._sync_locks_guard = threading.Lock()

    @property
    def platform_ready(self) -> bool:
        return bool(
            self._settings.google_integration_enabled
            and self._settings.google_oauth_client_id
            and self._settings.google_oauth_client_secret
            and self._settings.google_oauth_redirect_uri.startswith("https://")
        )

    @staticmethod
    def _require(context: AccessContext) -> None:
        if Permission.INTEGRATIONS_GOOGLE_MANAGE not in context.permissions:
            raise PermissionError("Sua conta não administra a integração Google.")

    @classmethod
    def _team_id(cls, context: AccessContext, requested: int | None = None) -> int:
        cls._require(context)
        teams = tuple(sorted(int(value) for value in context.team_ids))
        if requested is not None:
            if int(requested) not in teams:
                raise PermissionError("Este time não pertence à sua conta.")
            return int(requested)
        if len(teams) == 1:
            return teams[0]
        if not teams:
            raise PermissionError("Sua conta não possui um time ativo.")
        raise ValueError("Escolha qual time deseja conectar ao Google.")

    def _schema_ready(self) -> bool:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return bool(unit_of_work.integrations.is_available())

    def status(
        self,
        context: AccessContext,
        *,
        team_id: int | None = None,
    ) -> dict[str, Any]:
        selected = self._team_id(context, team_id)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            teams = unit_of_work.identity.get_teams_by_ids((selected,))
            team_name = str(teams[0]["display_name"]) if teams else f"Time {selected}"
            schema_ready = unit_of_work.integrations.is_available()
            connection = (
                unit_of_work.integrations.status(selected) if schema_ready else None
            )
        safe = dict(connection or {})
        for key in (
            "credential_ref",
            "google_subject",
            "connection_uuid",
            "granted_scopes_json",
        ):
            safe.pop(key, None)
        return {
            "platform_ready": self.platform_ready,
            "schema_ready": schema_ready,
            "team_id": selected,
            "team_name": team_name,
            "connection": safe or None,
            "calendar_authority": "HANDBALL",
            "public_fields": [
                "tipo e título",
                "data e horário",
                "local",
                "adversário",
                "situação",
            ],
            "never_public": [
                "notas internas",
                "nomes de atletas",
                "presenças e justificativas",
                "Playbook",
            ],
            "future_modules": ["Google Drive", "Google Sheets"],
        }

    def _sign(self, value: bytes) -> str:
        return hmac.new(
            self._settings.secret_key.encode("utf-8"),
            value,
            hashlib.sha256,
        ).hexdigest()

    def _pack_cookie(self, payload: Mapping[str, Any]) -> str:
        encoded = base64.urlsafe_b64encode(
            json.dumps(
                dict(payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).rstrip(b"=")
        return encoded.decode("ascii") + "." + self._sign(encoded)

    def _unpack_cookie(self, value: str) -> dict[str, Any]:
        try:
            encoded_text, signature = value.rsplit(".", 1)
            encoded = encoded_text.encode("ascii")
            if not hmac.compare_digest(signature, self._sign(encoded)):
                raise ValueError
            padded = encoded + b"=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GoogleIntegrationError(
                "google.oauth_state_invalid",
                "A autorização perdeu a validade. Comece novamente.",
            ) from exc
        if int(payload.get("expires_at") or 0) < int(time.time()):
            raise GoogleIntegrationError(
                "google.oauth_state_expired",
                "A autorização demorou demais. Comece novamente.",
            )
        return dict(payload)

    def begin_oauth(
        self,
        context: AccessContext,
        *,
        team_id: int | None = None,
    ) -> dict[str, str]:
        if not self.platform_ready:
            raise GoogleIntegrationError(
                "google.platform_not_ready",
                "O mantenedor ainda precisa preparar a conexão Google da plataforma.",
            )
        if not self._schema_ready():
            raise GoogleIntegrationError(
                "google.schema_not_ready",
                "A integração aguarda a atualização segura da base.",
            )
        selected = self._team_id(context, team_id)
        verifier = secrets.token_urlsafe(64)
        nonce = secrets.token_urlsafe(32)
        cookie = self._pack_cookie(
            {
                "nonce": nonce,
                "team_id": selected,
                "user_id": context.user_id,
                "session_id": context.session_id,
                "verifier": verifier,
                "expires_at": int(time.time()) + 600,
            }
        )
        url_state = nonce + "." + self._sign(
            f"{nonce}:{context.session_id}".encode("utf-8")
        )
        return {
            "authorization_url": self._oauth.authorization_url(
                state=url_state,
                code_challenge=pkce_challenge(verifier),
            ),
            "state_cookie": cookie,
        }

    def finish_oauth(
        self,
        context: AccessContext,
        *,
        code: str,
        state: str,
        state_cookie: str,
    ) -> dict[str, Any]:
        self._require(context)
        payload = self._unpack_cookie(state_cookie)
        expected_state = str(payload["nonce"]) + "." + self._sign(
            f"{payload['nonce']}:{context.session_id}".encode("utf-8")
        )
        if not hmac.compare_digest(state, expected_state):
            raise GoogleIntegrationError(
                "google.oauth_state_mismatch",
                "A autorização não corresponde a esta sessão. Comece novamente.",
            )
        if int(payload["user_id"]) != context.user_id or str(payload["session_id"]) != context.session_id:
            raise GoogleIntegrationError(
                "google.oauth_session_mismatch",
                "A autorização foi iniciada em outra sessão.",
            )
        team_id = self._team_id(context, int(payload["team_id"]))
        token = self._oauth.exchange_code(
            code=code,
            code_verifier=str(payload["verifier"]),
        )
        refresh_token = str(token.get("refresh_token") or "")
        if not refresh_token:
            raise GoogleIntegrationError(
                "google.refresh_token_missing",
                "O Google não liberou acesso contínuo. Tente conectar novamente.",
            )
        granted_scopes = set(str(token.get("scope") or "").split())
        required_scopes = {
            "https://www.googleapis.com/auth/calendar.app.created",
            "https://www.googleapis.com/auth/calendar.acls",
        }
        if not required_scopes.issubset(granted_scopes):
            self._oauth.revoke(refresh_token)
            raise GoogleIntegrationError(
                "google.required_permission_missing",
                "As duas permissões da agenda precisam ser aceitas para continuar.",
            )
        identity = self._oauth.user_identity(str(token["access_token"]))
        if not str(identity["email"]).casefold().endswith("@gmail.com"):
            self._oauth.revoke(refresh_token)
            raise GoogleIntegrationError(
                "google.gmail_required",
                "Escolha o endereço @gmail.com oficial do time.",
            )
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            current_connection = unit_of_work.integrations.status(team_id)
        if (
            current_connection
            and current_connection["status"] != "DISCONNECTED"
            and str(current_connection["google_subject"]) != str(identity["sub"])
        ):
            raise GoogleIntegrationError(
                "google.account_change_requires_disconnect",
                "Desconecte a conta atual antes de escolher outro Gmail.",
            )
        reference = str(uuid4())
        stored = {
            "refresh_token": refresh_token,
            "token_type": str(token.get("token_type") or "Bearer"),
            "scope": str(token.get("scope") or " ".join(GOOGLE_SCOPES)),
        }
        self._token_vault.save(reference, stored)
        previous_reference: str | None = None
        try:
            with self._unit_of_work_factory() as unit_of_work:
                previous = unit_of_work.integrations.status(team_id)
                previous_reference = (
                    str(previous.get("credential_ref") or "") if previous else None
                )
                connection = unit_of_work.integrations.upsert_connection(
                    {
                        "team_id": team_id,
                        "connection_uuid": (
                            previous.get("connection_uuid")
                            if previous and previous.get("google_subject") == identity["sub"]
                            else str(uuid4())
                        ),
                        "google_subject": identity["sub"],
                        "account_email": identity["email"],
                        "granted_scopes": str(stored["scope"]).split(),
                        "credential_ref": reference,
                        "connected_by_user_id": context.user_id,
                    }
                )
        except Exception:
            self._token_vault.delete(reference)
            raise
        if previous_reference and previous_reference != reference:
            self._token_vault.delete(previous_reference)
        return {
            "team_id": team_id,
            "account_email": connection["account_email"],
            "status": connection["status"],
        }

    def _connection(self, team_id: int) -> dict[str, Any]:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            connection = unit_of_work.integrations.status(team_id)
        if connection is None or connection["status"] == "DISCONNECTED":
            raise GoogleIntegrationError(
                "google.not_connected",
                "Conecte o Gmail do time antes de continuar.",
            )
        return connection

    def _access_token(self, team_id: int) -> tuple[dict[str, Any], str]:
        connection = self._connection(team_id)
        credential = self._token_vault.load(str(connection["credential_ref"]))
        try:
            refreshed = self._oauth.refresh_access_token(
                str(credential["refresh_token"])
            )
        except GoogleIntegrationError as exc:
            if exc.code == "google.reauth_required":
                with self._unit_of_work_factory() as unit_of_work:
                    unit_of_work.integrations.set_connection_status(
                        team_id,
                        "REAUTH_REQUIRED",
                        actor_user_id=int(connection["connected_by_user_id"]),
                        audit_action="google.connection.reauth_required",
                    )
            raise
        return connection, str(refreshed["access_token"])

    def setup_calendar(
        self,
        context: AccessContext,
        *,
        team_id: int | None = None,
    ) -> dict[str, Any]:
        selected = self._team_id(context, team_id)
        connection, access_token = self._access_token(selected)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            teams = unit_of_work.identity.get_teams_by_ids((selected,))
        team_name = str(teams[0]["display_name"]) if teams else f"Time {selected}"
        calendar_id = str(connection.get("calendar_id") or "")
        calendar_name = str(connection.get("calendar_name") or f"{team_name} — Agenda")
        if not calendar_id:
            created = self._calendar.create_calendar(
                access_token,
                f"{team_name} — Agenda",
            )
            calendar_id = str(created["id"])
            calendar_name = str(created.get("summary") or f"{team_name} — Agenda")
        self._calendar.make_public(access_token, calendar_id)
        with self._unit_of_work_factory() as unit_of_work:
            result = unit_of_work.integrations.save_calendar(
                selected,
                {
                    "calendar_id": calendar_id,
                    "calendar_name": calendar_name,
                    "public_url": self._calendar.public_url(calendar_id),
                    "is_public": True,
                },
                actor_user_id=context.user_id,
            )
            unit_of_work.integrations.enqueue_reconcile(selected)
        sync = self.sync_team(selected)
        return {"connection": self._safe_connection(result), "sync": sync}

    @staticmethod
    def _safe_connection(connection: Mapping[str, Any]) -> dict[str, Any]:
        safe = dict(connection)
        for key in ("credential_ref", "google_subject", "connection_uuid"):
            safe.pop(key, None)
        return safe

    def update_settings(
        self,
        context: AccessContext,
        payload: Mapping[str, Any],
        *,
        team_id: int | None = None,
    ) -> dict[str, Any]:
        selected = self._team_id(context, team_id)
        with self._unit_of_work_factory() as unit_of_work:
            result = unit_of_work.integrations.update_settings(
                selected,
                payload,
                actor_user_id=context.user_id,
            )
            unit_of_work.integrations.enqueue_reconcile(selected)
        self.request_sync(selected)
        return self._safe_connection(result)

    def pause(self, context: AccessContext, *, team_id: int | None = None) -> dict[str, Any]:
        selected = self._team_id(context, team_id)
        with self._unit_of_work_factory() as unit_of_work:
            result = unit_of_work.integrations.set_connection_status(
                selected,
                "PAUSED",
                actor_user_id=context.user_id,
                audit_action="google.connection.pause",
            )
        return self._safe_connection(result)

    def resume(self, context: AccessContext, *, team_id: int | None = None) -> dict[str, Any]:
        selected = self._team_id(context, team_id)
        with self._unit_of_work_factory() as unit_of_work:
            result = unit_of_work.integrations.set_connection_status(
                selected,
                "CONNECTED",
                actor_user_id=context.user_id,
                audit_action="google.connection.resume",
            )
            unit_of_work.integrations.enqueue_reconcile(selected)
        self.request_sync(selected)
        return self._safe_connection(result)

    def disconnect(
        self,
        context: AccessContext,
        *,
        team_id: int | None,
        connection_version: int,
        make_calendar_private: bool,
    ) -> dict[str, Any]:
        selected = self._team_id(context, team_id)
        connection, access_token = self._access_token(selected)
        if int(connection["version"]) != int(connection_version):
            raise GoogleIntegrationError(
                "google.connection_changed",
                "A conexão mudou. Recarregue antes de desconectar.",
            )
        if not make_calendar_private:
            raise GoogleIntegrationError(
                "google.private_required",
                "Por segurança, o calendário precisa ficar privado antes de desconectar.",
            )
        if connection.get("calendar_id"):
            self._calendar.make_private(access_token, str(connection["calendar_id"]))
        credential = self._token_vault.load(str(connection["credential_ref"]))
        revocation_confirmed = self._oauth.revoke(str(credential["refresh_token"]))
        with self._unit_of_work_factory() as unit_of_work:
            result = unit_of_work.integrations.disconnect(
                selected,
                actor_user_id=context.user_id,
            )
        self._token_vault.delete(str(connection["credential_ref"]))
        return {
            "connection": self._safe_connection(result),
            "revocation_confirmed": revocation_confirmed,
        }

    @staticmethod
    def _google_event_id(connection_uuid: str, event_id: int) -> str:
        digest = hashlib.sha256(
            f"{connection_uuid}:{int(event_id)}".encode("utf-8")
        ).hexdigest()
        return "hb" + digest[:40]

    @staticmethod
    def _event_summary(event: Mapping[str, Any]) -> str:
        event_type = str(event["event_type"])
        title = str(event.get("title") or "").strip()
        opponent = str(event.get("opponent") or "").strip()
        if event_type == "TRAINING":
            base = title or "Treino"
        elif event_type == "GAME":
            base = title or (f"Jogo — {opponent}" if opponent else "Jogo")
        else:
            base = title or "Campeonato"
        status = str(event["status"])
        if status == "CANCELLED":
            return f"CANCELADO — {base}"
        if status == "RESCHEDULED":
            return f"REAGENDADO — {base}"
        return base

    @staticmethod
    def _event_payload(event: Mapping[str, Any]) -> dict[str, Any]:
        status_labels = {
            "PLANNED": "Planejado",
            "CONFIRMED": "Confirmado",
            "CANCELLED": "Cancelado",
            "RESCHEDULED": "Reagendado",
            "COMPLETED": "Concluído",
        }
        starts_at = str(event["starts_at"])
        ends_at = str(event["ends_at"])
        if event.get("all_day"):
            start_date = datetime.fromisoformat(starts_at.replace("Z", "+00:00")).date()
            end_date = datetime.fromisoformat(ends_at.replace("Z", "+00:00")).date()
            if end_date <= start_date:
                end_date = start_date + timedelta(days=1)
            start: dict[str, str] = {"date": start_date.isoformat()}
            end: dict[str, str] = {"date": end_date.isoformat()}
        else:
            start = {"dateTime": starts_at, "timeZone": "America/Sao_Paulo"}
            end = {"dateTime": ends_at, "timeZone": "America/Sao_Paulo"}
        return {
            "summary": GoogleIntegrationService._event_summary(event),
            "description": (
                f"Situação: {status_labels.get(str(event['status']), str(event['status']))}.\n"
                "Agenda pública atualizada pelo Handball."
            ),
            "location": str(event.get("location") or ""),
            "start": start,
            "end": end,
            "visibility": "public",
            "transparency": "opaque",
            "extendedProperties": {
                "private": {
                    "handball_event_id": str(event["id"]),
                    "handball_team_id": str(event["team_id"]),
                    "handball_version": str(event.get("version") or 1),
                }
            },
        }

    def _process_event(self, team_id: int, operation: Mapping[str, Any]) -> None:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            connection = unit_of_work.integrations.status(team_id)
            event = unit_of_work.integrations.event_for_sync(
                team_id,
                int(operation["aggregate_id"]),
            )
        if connection is None or event is None or not connection.get("calendar_id"):
            raise GoogleIntegrationError(
                "google.event_unavailable",
                "O evento ou calendário não está mais disponível.",
            )
        _, access_token = self._access_token(team_id)
        google_event_id = self._google_event_id(
            str(connection["connection_uuid"]), int(event["id"])
        )
        remote = self._calendar.upsert_event(
            access_token,
            calendar_id=str(connection["calendar_id"]),
            google_event_id=google_event_id,
            event=self._event_payload(event),
        )
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.integrations.upsert_event_link(
                {
                    "calendar_event_id": event["id"],
                    "connection_id": connection["id"],
                    "google_event_id": google_event_id,
                    "google_etag": remote.get("etag") or "",
                    "last_local_version": event.get("version") or 1,
                }
            )

    def _process_delete_event(
        self,
        team_id: int,
        operation: Mapping[str, Any],
    ) -> None:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            connection = unit_of_work.integrations.status(team_id)
            link = (
                unit_of_work.integrations.event_link(
                    int(connection["id"]), int(operation["aggregate_id"])
                )
                if connection is not None
                else None
            )
        if connection is None or not connection.get("calendar_id") or link is None:
            return
        _, access_token = self._access_token(team_id)
        self._calendar.delete_event(
            access_token,
            calendar_id=str(connection["calendar_id"]),
            google_event_id=str(link["google_event_id"]),
        )
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.integrations.delete_event_link(
                int(connection["id"]), int(operation["aggregate_id"])
            )

    def sync_team(self, team_id: int) -> dict[str, Any]:
        lock = self._lock_for(team_id)
        if not lock.acquire(blocking=False):
            return {"status": "already_running", "processed": 0, "failed": 0}
        processed = 0
        failed = 0
        try:
            for _ in range(10):
                with self._unit_of_work_factory() as unit_of_work:
                    operations = unit_of_work.integrations.claim_ready(team_id, limit=50)
                if not operations:
                    break
                for operation in operations:
                    try:
                        if operation["action"] == "RECONCILE_CALENDAR":
                            with self._unit_of_work_factory() as unit_of_work:
                                removals = unit_of_work.integrations.linked_events_outside_policy(team_id)
                                for event in removals:
                                    unit_of_work.integrations.enqueue_delete_event(int(event["id"]))
                                events = unit_of_work.integrations.events_for_active_season(team_id)
                                for event in events:
                                    unit_of_work.integrations.enqueue_event(int(event["id"]))
                        elif operation["action"] == "UPSERT_EVENT":
                            self._process_event(team_id, operation)
                        elif operation["action"] == "DELETE_EVENT":
                            self._process_delete_event(team_id, operation)
                        else:
                            raise GoogleIntegrationError(
                                "google.operation_unknown",
                                "A operação de sincronização é desconhecida.",
                            )
                        with self._unit_of_work_factory() as unit_of_work:
                            unit_of_work.integrations.mark_succeeded(
                                str(operation["operation_id"])
                            )
                        processed += 1
                    except GoogleIntegrationError as exc:
                        with self._unit_of_work_factory() as unit_of_work:
                            unit_of_work.integrations.mark_failed(
                                str(operation["operation_id"]),
                                code=exc.code,
                                message=str(exc),
                                retryable=exc.retryable,
                            )
                            unit_of_work.integrations.record_sync_result(
                                team_id,
                                status="ERROR",
                                code=exc.code,
                                message=str(exc),
                            )
                        failed += 1
                    except Exception as exc:
                        with self._unit_of_work_factory() as unit_of_work:
                            unit_of_work.integrations.mark_failed(
                                str(operation["operation_id"]),
                                code="google.unexpected_sync_error",
                                message="Falha temporária ao sincronizar com o Google.",
                                retryable=True,
                            )
                            unit_of_work.integrations.record_sync_result(
                                team_id,
                                status="ERROR",
                                code="google.unexpected_sync_error",
                                message="Falha temporária ao sincronizar com o Google.",
                            )
                        failed += 1
                if failed:
                    break
            if not failed:
                with self._unit_of_work_factory() as unit_of_work:
                    unit_of_work.integrations.record_sync_result(team_id, status="OK")
            return {
                "status": "ok" if not failed else "partial",
                "processed": processed,
                "failed": failed,
            }
        finally:
            lock.release()

    def sync_now(
        self,
        context: AccessContext,
        *,
        team_id: int | None = None,
    ) -> dict[str, Any]:
        selected = self._team_id(context, team_id)
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.integrations.enqueue_reconcile(selected)
        return self.sync_team(selected)

    def _lock_for(self, team_id: int) -> threading.Lock:
        with self._sync_locks_guard:
            return self._sync_locks.setdefault(int(team_id), threading.Lock())

    def request_sync(self, team_id: int) -> None:
        if not self.platform_ready:
            return
        thread = threading.Thread(
            target=self.sync_team,
            args=(int(team_id),),
            name=f"google-sync-{int(team_id)}",
            daemon=True,
        )
        thread.start()
