from __future__ import annotations

from pathlib import Path

from handball.core.authorization import Permission, ROLE_PERMISSIONS
from handball.database.migrations import (
    DatabaseMigrator,
    MIGRATION_V3_CHECKSUM,
    logical_fingerprint,
    verify_database,
)
from tests.test_users_authorization import login, logout, make_v2


def _options(client):
    response = client.get("/api/v1/calendar/options")
    assert response.status_code == 200
    payload = response.json()
    team = payload["teams"][0]
    season = next(
        item for item in payload["seasons"] if item["label"] == "2026.2"
    )
    assert season["starts_on"] is None
    assert season["ends_on"] is None
    return int(team["id"]), int(season["id"])


def _event(
    team_id: int,
    season_id: int,
    *,
    event_type: str = "TRAINING",
    status: str = "PLANNED",
    starts_at: str = "2035-08-01T19:00:00-03:00",
    ends_at: str = "2035-08-01T21:00:00-03:00",
    restriction_kind: str | None = None,
    attendance_session_id: int | None = None,
) -> dict[str, object]:
    return {
        "team_id": team_id,
        "season_id": season_id,
        "event_type": event_type,
        "status": status,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "location": "CEPEUSP",
        "notes": "Planejamento de teste",
        "restriction_kind": restriction_kind,
        "attendance_session_id": attendance_session_id,
    }


def test_v3_migration_is_versioned_integral_and_keeps_open_season_dates(
    tmp_path: Path,
) -> None:
    client, manager, data = make_v2(tmp_path)

    status = DatabaseMigrator(manager.db_path).status()
    verification = verify_database(manager.db_path)
    assert status.current_version == 3
    assert status.pending_versions == ()
    assert status.compatible is True
    assert verification["ok"] is True

    with manager.read_only_connection() as connection:
        row = connection.execute(
            "SELECT name,checksum_sha256 FROM schema_migrations WHERE version=3"
        ).fetchone()
        season = connection.execute(
            "SELECT label,starts_on,ends_on FROM seasons WHERE label='2026.2'"
        ).fetchone()
        tables = {
            item[0]
            for item in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            )
        }
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert row["name"] == "calendar_events_justifications"
    assert row["checksum_sha256"] == MIGRATION_V3_CHECKSUM
    assert tuple(season) == ("2026.2", None, None)
    assert {"calendar_events", "calendar_justifications"} <= tables
    assert client.get("/ready").json()["schema_version"] == 3
    assert data["before_ids"]


def test_ct_manages_scoped_events_without_creating_attendance(
    tmp_path: Path,
) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    with manager.read_only_connection() as connection:
        before_sessions = connection.execute(
            "SELECT COUNT(*) FROM training_sessions"
        ).fetchone()[0]

    assert client.post(
        "/api/v1/calendar/events",
        json=_event(team_id, season_id),
    ).status_code == 403
    created = client.post(
        "/api/v1/calendar/events",
        json=_event(team_id, season_id),
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    event_id = int(created.json()["id"])

    updated_body = _event(
        team_id,
        season_id,
        status="CONFIRMED",
        starts_at="2035-08-01T20:00:00-03:00",
        ends_at="2035-08-01T22:00:00-03:00",
    )
    updated = client.put(
        f"/api/v1/calendar/events/{event_id}",
        json=updated_body,
        headers={"X-CSRF-Token": csrf},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "CONFIRMED"
    assert updated.json()["attendance_session_id"] is None

    with manager.read_only_connection() as connection:
        after_sessions = connection.execute(
            "SELECT COUNT(*) FROM training_sessions"
        ).fetchone()[0]
        audit_actions = {
            row[0]
            for row in connection.execute(
                """SELECT action FROM security_audit_events
                   WHERE entity='calendar_event'"""
            )
        }
    assert after_sessions == before_sessions
    assert audit_actions == {"calendar.event.create", "calendar.event.update"}


def test_past_present_future_restrictions_and_calendar_page(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    bodies = [
        _event(
            team_id,
            season_id,
            starts_at="2020-01-01T10:00:00-03:00",
            ends_at="2020-01-01T12:00:00-03:00",
        ),
        _event(
            team_id,
            season_id,
            event_type="GAME",
            starts_at="2000-01-01T00:00:00-03:00",
            ends_at="2100-01-01T00:00:00-03:00",
        ),
        _event(team_id, season_id),
        _event(
            team_id,
            season_id,
            event_type="COLLECTIVE_RESTRICTION",
            restriction_kind="COURT_UNAVAILABLE",
        ),
    ]
    for body in bodies:
        response = client.post(
            "/api/v1/calendar/events",
            json=body,
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 201, response.text

    invalid = client.post(
        "/api/v1/calendar/events",
        json=_event(
            team_id,
            season_id,
            event_type="COLLECTIVE_RESTRICTION",
        ),
        headers={"X-CSRF-Token": csrf},
    )
    assert invalid.status_code == 422
    calendar = client.get("/api/v1/calendar").json()
    assert len(calendar["groups"]["past"]) == 1
    assert len(calendar["groups"]["present"]) == 1
    assert len(calendar["groups"]["future"]) == 2
    page = client.get("/app/calendario")
    assert page.status_code == 200
    assert "Presença continua sendo o ocorrido" in page.text
    assert "/static/calendar.js" in page.text


def test_player_sees_team_events_and_only_writes_own_justification(
    tmp_path: Path,
) -> None:
    client, manager, data = make_v2(tmp_path)
    ct_csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    training = client.post(
        "/api/v1/calendar/events",
        json=_event(team_id, season_id),
        headers={"X-CSRF-Token": ct_csrf},
    ).json()
    championship = client.post(
        "/api/v1/calendar/events",
        json=_event(team_id, season_id, event_type="CHAMPIONSHIP"),
        headers={"X-CSRF-Token": ct_csrf},
    ).json()
    with manager.unit_of_work() as unit_of_work:
        now = "2026-07-26T12:00:00+00:00"
        other_team_id = int(
            unit_of_work.connection.execute(
                """INSERT INTO teams(
                       code,slug,display_name,active,created_at,updated_at
                   ) VALUES('OTHER','other','Outra equipe',1,?,?)""",
                (now, now),
            ).lastrowid
        )
        other_season_id = int(
            unit_of_work.connection.execute(
                """INSERT INTO seasons(
                       team_id,label,starts_on,ends_on,active
                   ) VALUES(?,'2026.2',NULL,NULL,1)""",
                (other_team_id,),
            ).lastrowid
        )
        unit_of_work.calendar.create_event(
            _event(other_team_id, other_season_id),
            actor_user_id=1,
        )
    assert client.post(
        "/api/v1/calendar/events",
        json=_event(other_team_id, other_season_id),
        headers={"X-CSRF-Token": ct_csrf},
    ).status_code == 403
    assert {
        item["team_id"] for item in client.get("/api/v1/calendar").json()["items"]
    } == {team_id}
    logout(client)

    player_csrf = login(client, "player", data["passwords"]["player"])
    page = client.get("/app/calendario")
    assert page.status_code == 200
    assert "calendar-event-form" not in page.text
    player_events = client.get("/api/v1/calendar").json()["items"]
    assert len(player_events) == 2
    assert {item["team_id"] for item in player_events} == {team_id}
    assert client.post(
        "/api/v1/calendar/events",
        json=_event(team_id, season_id),
        headers={"X-CSRF-Token": player_csrf},
    ).status_code == 403

    saved = client.post(
        f"/api/v1/calendar/events/{training['id']}/justification",
        json={"reason": "Compromisso acadêmico"},
        headers={"X-CSRF-Token": player_csrf},
    )
    assert saved.status_code == 200
    justification_id = int(saved.json()["id"])
    changed = client.put(
        f"/api/v1/calendar/justifications/{justification_id}",
        json={"reason": "Prova acadêmica"},
        headers={"X-CSRF-Token": player_csrf},
    )
    assert changed.status_code == 200
    denied = client.post(
        f"/api/v1/calendar/events/{championship['id']}/justification",
        json={"reason": "Não se aplica"},
        headers={"X-CSRF-Token": player_csrf},
    )
    assert denied.status_code == 400

    with manager.read_only_connection() as connection:
        justifications = connection.execute(
            "SELECT player_member_id,reason FROM calendar_justifications"
        ).fetchall()
        attendance_count = connection.execute(
            "SELECT COUNT(*) FROM attendance_records"
        ).fetchone()[0]
        event_status = connection.execute(
            "SELECT status FROM calendar_events WHERE id=?",
            (training["id"],),
        ).fetchone()[0]
    assert [(row[0], row[1]) for row in justifications] == [
        (data["player_member_id"], "Prova acadêmica")
    ]
    assert attendance_count == 0
    assert event_status == "PLANNED"


def test_calendar_is_default_deny_for_dev_and_empty_scope(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "dev", data["passwords"]["dev"])
    assert Permission.CALENDAR_READ_TEAM not in ROLE_PERMISSIONS["DEV"]
    assert client.get("/api/v1/calendar").status_code == 403
    assert client.get("/app/calendario").status_code == 403
