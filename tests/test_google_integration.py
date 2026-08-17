from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from handball.integrations.google import (
    GOOGLE_SCOPES,
    GoogleCalendarClient,
    GoogleOAuthClient,
    MemoryTokenVault,
)
from tests.test_users_authorization import login, logout, make_v2


class FakeGoogleOAuth:
    def __init__(self) -> None:
        self.revoked: list[str] = []

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        return (
            "https://accounts.google.test/authorize?"
            f"state={state}&code_challenge={code_challenge}"
        )

    def exchange_code(self, *, code: str, code_verifier: str):
        assert code == "authorization-code"
        assert len(code_verifier) > 40
        return {
            "access_token": "access-from-code",
            "refresh_token": "refresh-team-only",
            "token_type": "Bearer",
            "scope": (
                "openid email "
                "https://www.googleapis.com/auth/calendar.app.created "
                "https://www.googleapis.com/auth/calendar.acls"
            ),
        }

    def user_identity(self, access_token: str):
        assert access_token == "access-from-code"
        return {"sub": "google-team-subject", "email": "time.oficial@gmail.com"}

    def refresh_access_token(self, refresh_token: str):
        assert refresh_token == "refresh-team-only"
        return {"access_token": "fresh-access"}

    def revoke(self, token: str) -> bool:
        self.revoked.append(token)
        return True


class FakeGoogleCalendar:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.public: list[str] = []
        self.private: list[str] = []
        self.upserted: list[dict[str, object]] = []
        self.deleted: list[str] = []

    def create_calendar(self, access_token: str, name: str):
        assert access_token == "fresh-access"
        self.created.append(name)
        return {"id": "team-calendar@group.calendar.google.com", "summary": name}

    def make_public(self, access_token: str, calendar_id: str) -> None:
        assert access_token == "fresh-access"
        self.public.append(calendar_id)

    def make_private(self, access_token: str, calendar_id: str) -> None:
        assert access_token == "fresh-access"
        self.private.append(calendar_id)

    @staticmethod
    def public_url(calendar_id: str) -> str:
        return f"https://calendar.google.test/embed?src={calendar_id}"

    def upsert_event(
        self,
        access_token: str,
        *,
        calendar_id: str,
        google_event_id: str,
        event,
    ):
        assert access_token == "fresh-access"
        assert calendar_id == "team-calendar@group.calendar.google.com"
        self.upserted.append(
            {"google_event_id": google_event_id, "event": dict(event)}
        )
        return {"id": google_event_id, "etag": f"etag-{len(self.upserted)}"}

    def delete_event(
        self,
        access_token: str,
        *,
        calendar_id: str,
        google_event_id: str,
    ) -> None:
        assert access_token == "fresh-access"
        assert calendar_id == "team-calendar@group.calendar.google.com"
        self.deleted.append(google_event_id)


def _prepare_google(client):
    service = client.app.state.google_integration_service
    oauth = FakeGoogleOAuth()
    calendar = FakeGoogleCalendar()
    vault = MemoryTokenVault()
    service._settings = replace(
        service._settings,
        google_integration_enabled=True,
        google_oauth_client_id="client-id",
        google_oauth_client_secret="client-secret",
        google_oauth_redirect_uri=(
            "https://testserver/api/v1/integrations/google/oauth/callback"
        ),
    )
    service._oauth = oauth
    service._calendar = calendar
    service._token_vault = vault
    return service, oauth, calendar, vault


def test_google_http_adapters_use_declared_scopes_and_calendar_endpoints() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "scope": " ".join(GOOGLE_SCOPES),
                },
            )
        if path.endswith("/v1/userinfo"):
            return httpx.Response(
                200, json={"sub": "subject", "email": "time@gmail.com"}
            )
        if path.endswith("/revoke"):
            return httpx.Response(200)
        if path.endswith("/calendar/v3/calendars"):
            return httpx.Response(
                200, json={"id": "team@calendar", "summary": "Time — Agenda"}
            )
        if path.endswith("/acl") and request.method == "POST":
            return httpx.Response(200, json={"id": "default"})
        if path.endswith("/acl/default") and request.method == "DELETE":
            return httpx.Response(204)
        if "/events/hbevent" in path and request.method == "GET":
            return httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})
        if path.endswith("/events") and request.method == "POST":
            return httpx.Response(200, json={"id": "hbevent", "etag": "etag"})
        if "/events/hbevent" in path and request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError(f"Requisição inesperada: {request.method} {path}")

    transport = httpx.MockTransport(handler)
    oauth = GoogleOAuthClient(
        client_id="client",
        client_secret="secret",
        redirect_uri="https://handball.test/oauth/callback",
        transport=transport,
    )
    authorization = parse_qs(
        urlparse(oauth.authorization_url(state="state", code_challenge="pkce")).query
    )
    assert set(authorization["scope"][0].split()) == set(GOOGLE_SCOPES)
    assert authorization["access_type"] == ["offline"]
    assert authorization["code_challenge_method"] == ["S256"]
    assert oauth.exchange_code(code="code", code_verifier="verifier")["refresh_token"] == "refresh"
    assert oauth.refresh_access_token("refresh")["access_token"] == "access"
    assert oauth.user_identity("access")["email"] == "time@gmail.com"
    assert oauth.revoke("refresh") is True

    calendar = GoogleCalendarClient(transport=transport)
    created = calendar.create_calendar("access", "Time — Agenda")
    assert created["id"] == "team@calendar"
    calendar.make_public("access", created["id"])
    remote = calendar.upsert_event(
        "access",
        calendar_id=created["id"],
        google_event_id="hbevent",
        event={
            "summary": "Treino",
            "start": {"dateTime": "2035-01-01T19:00:00-03:00"},
            "end": {"dateTime": "2035-01-01T21:00:00-03:00"},
        },
    )
    assert remote["etag"] == "etag"
    calendar.delete_event(
        "access", calendar_id=created["id"], google_event_id="hbevent"
    )
    calendar.make_private("access", created["id"])
    assert ("POST", "/calendar/v3/calendars") in requests
    assert any(method == "POST" and path.endswith("/events") for method, path in requests)


def test_google_module_is_guided_ct_only_and_has_public_disclosures(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    assert client.get("/google-integration").status_code == 200
    privacy = client.get("/privacy/google-integration")
    assert privacy.status_code == 200
    assert "não lê Gmail, Drive, Planilhas" in privacy.text

    login(client, "player", data["passwords"]["player"])
    assert client.get("/app/integracoes/google").status_code == 403
    assert client.get("/api/v1/integrations/google").status_code == 403
    assert "Integração Google" not in client.get("/app").text
    logout(client)

    login(client, "ct", data["passwords"]["ct"])
    page = client.get("/app/integracoes/google")
    assert page.status_code == 200
    assert "Google do time, sem complicação" in page.text
    assert "PASSO 1 DE 4" in page.text
    assert "O que nunca sai do sistema" in page.text
    assert "Integração Google" in client.get("/app").text


def test_google_oauth_calendar_outbox_settings_and_disconnect(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    service, oauth, calendar, vault = _prepare_google(client)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id = int(data["team_id"])

    initial = client.get(
        "/api/v1/integrations/google", params={"team_id": team_id}
    )
    assert initial.status_code == 200
    assert initial.json()["platform_ready"] is True
    assert initial.json()["connection"] is None
    assert client.post(
        "/api/v1/integrations/google/oauth/start", json={"team_id": team_id}
    ).status_code == 403

    started = client.post(
        "/api/v1/integrations/google/oauth/start",
        json={"team_id": team_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert started.status_code == 200, started.text
    authorization_url = started.json()["authorization_url"]
    state = parse_qs(urlparse(authorization_url).query)["state"][0]
    callback = client.get(
        "/api/v1/integrations/google/oauth/callback",
        params={"code": "authorization-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"].endswith("?google=connected")

    connected = client.get(
        "/api/v1/integrations/google", params={"team_id": team_id}
    ).json()["connection"]
    assert connected["account_email"] == "time.oficial@gmail.com"
    assert "credential_ref" not in connected

    setup = client.post(
        "/api/v1/integrations/google/calendar/setup",
        json={"team_id": team_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert setup.status_code == 200, setup.text
    assert calendar.created and calendar.public
    assert setup.json()["connection"]["is_public"] is True
    assert b"refresh-team-only" not in manager.db_path.read_bytes()

    requested: list[int] = []
    service.request_sync = lambda selected: requested.append(int(selected))
    client.app.state.calendar_service._integration_sync_request = service.request_sync
    options = client.get("/api/v1/calendar/options").json()
    season_id = next(
        item["id"] for item in options["seasons"] if item["label"] == "2026.2"
    )
    created = client.post(
        "/api/v1/calendar/events",
        json={
            "team_id": team_id,
            "season_id": season_id,
            "event_type": "TRAINING",
            "status": "PLANNED",
            "starts_at": "2036-09-01T19:00:00-03:00",
            "ends_at": "2036-09-01T21:00:00-03:00",
            "location": "CEPEUSP",
            "notes": "segredo interno que não pode sair",
            "title": "Treino coletivo",
            "opponent": "",
            "all_day": False,
            "restriction_kind": None,
            "attendance_session_id": None,
            "is_player_visible": False,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201, created.text
    event_id = int(created.json()["id"])
    assert requested == [team_id]
    with manager.read_only_connection() as connection:
        queued = connection.execute(
            """SELECT action,status FROM integration_outbox
               WHERE aggregate_type='CALENDAR_EVENT' AND aggregate_id=?
               ORDER BY created_at DESC LIMIT 1""",
            (event_id,),
        ).fetchone()
    assert tuple(queued) == ("UPSERT_EVENT", "PENDING")

    synced = service.sync_team(team_id)
    assert synced["failed"] == 0
    sent = next(
        item for item in calendar.upserted
        if item["event"]["extendedProperties"]["private"]["handball_event_id"]
        == str(event_id)
    )
    serialized = str(sent["event"])
    assert "Treino coletivo" in serialized
    assert "segredo interno" not in serialized
    assert "athlete" not in serialized.casefold()

    settings = client.put(
        "/api/v1/integrations/google/calendar/settings",
        json={
            "team_id": team_id,
            "publish_trainings": False,
            "publish_games": True,
            "publish_championships": True,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert settings.status_code == 200, settings.text
    service.sync_team(team_id)
    assert sent["google_event_id"] in calendar.deleted

    reenabled = client.put(
        "/api/v1/integrations/google/calendar/settings",
        json={
            "team_id": team_id,
            "publish_trainings": True,
            "publish_games": True,
            "publish_championships": True,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert reenabled.status_code == 200, reenabled.text
    service.sync_team(team_id)
    assert sum(
        item["google_event_id"] == sent["google_event_id"]
        for item in calendar.upserted
    ) == 2

    paused = client.post(
        "/api/v1/integrations/google/pause",
        json={"team_id": team_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert paused.json()["status"] == "PAUSED"
    resumed = client.post(
        "/api/v1/integrations/google/resume",
        json={"team_id": team_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert resumed.json()["status"] == "CONNECTED"

    version = int(resumed.json()["version"])
    disconnected = client.post(
        "/api/v1/integrations/google/disconnect",
        json={
            "team_id": team_id,
            "connection_version": version,
            "make_calendar_private": True,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert disconnected.status_code == 200, disconnected.text
    assert disconnected.json()["connection"]["status"] == "DISCONNECTED"
    assert disconnected.json()["revocation_confirmed"] is True
    assert calendar.private == ["team-calendar@group.calendar.google.com"]
    assert oauth.revoked == ["refresh-team-only"]
    assert vault._tokens == {}
