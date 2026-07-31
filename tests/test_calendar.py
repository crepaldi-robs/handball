from __future__ import annotations

from datetime import date
from pathlib import Path

from handball.core.authorization import Permission, ROLE_PERMISSIONS
from handball.database.migrations import (
    DatabaseMigrator,
    MIGRATION_V3_CHECKSUM,
    MIGRATION_V4_CHECKSUM,
    MIGRATION_V7_CHECKSUM,
    MIGRATION_V8_CHECKSUM,
    MIGRATION_V9_CHECKSUM,
    MIGRATION_V10_CHECKSUM,
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
    is_player_visible: bool = False,
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
        "is_player_visible": is_player_visible,
    }


def test_v4_migration_is_versioned_integral_and_keeps_open_season_dates(
    tmp_path: Path,
) -> None:
    client, manager, data = make_v2(tmp_path)

    status = DatabaseMigrator(manager.db_path).status()
    verification = verify_database(manager.db_path)
    assert status.current_version == 10
    assert status.pending_versions == ()
    assert status.compatible is True
    assert verification["ok"] is True

    with manager.read_only_connection() as connection:
        row = connection.execute(
            "SELECT name,checksum_sha256 FROM schema_migrations WHERE version=3"
        ).fetchone()
        v4_row = connection.execute(
            "SELECT name,checksum_sha256 FROM schema_migrations WHERE version=4"
        ).fetchone()
        v7_row = connection.execute(
            "SELECT name,checksum_sha256 FROM schema_migrations WHERE version=7"
        ).fetchone()
        v8_row = connection.execute(
            "SELECT name,checksum_sha256 FROM schema_migrations WHERE version=8"
        ).fetchone()
        v9_row = connection.execute(
            "SELECT name,checksum_sha256 FROM schema_migrations WHERE version=9"
        ).fetchone()
        v10_row = connection.execute(
            "SELECT name,checksum_sha256 FROM schema_migrations WHERE version=10"
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
    assert v4_row["name"] == "calendar_attendance_source_of_truth"
    assert v4_row["checksum_sha256"] == MIGRATION_V4_CHECKSUM
    assert tuple(season) == ("2026.2", None, None)
    assert v7_row["name"] == "calendar_professional_workflow"
    assert v7_row["checksum_sha256"] == MIGRATION_V7_CHECKSUM
    assert v8_row["name"] == "playbook_library_and_training_plans"
    assert v8_row["checksum_sha256"] == MIGRATION_V8_CHECKSUM
    assert v9_row["name"] == "calendar_countdown_targets"
    assert v9_row["checksum_sha256"] == MIGRATION_V9_CHECKSUM
    assert v10_row["name"] == "playbook_independent_plans_and_player_calendar_visibility"
    assert v10_row["checksum_sha256"] == MIGRATION_V10_CHECKSUM
    assert {
        "calendar_events",
        "calendar_justifications",
        "calendar_event_series",
        "calendar_event_transitions",
        "calendar_command_receipts",
    } <= tables
    assert client.get("/ready").json()["schema_version"] == 10
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


def test_countdown_target_counts_only_active_trainings_before_championship(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)

    for starts_at, ends_at, status in (
        ("2026-11-10T19:00:00-03:00", "2026-11-10T21:00:00-03:00", "PLANNED"),
        ("2026-11-17T19:00:00-03:00", "2026-11-17T21:00:00-03:00", "CONFIRMED"),
        ("2026-11-18T19:00:00-03:00", "2026-11-18T21:00:00-03:00", "CANCELLED"),
        ("2026-11-24T19:00:00-03:00", "2026-11-24T21:00:00-03:00", "PLANNED"),
    ):
        response = client.post(
            "/api/v1/calendar/events",
            json=_event(
                team_id,
                season_id,
                status=status,
                starts_at=starts_at,
                ends_at=ends_at,
            ),
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 201, response.text

    bife = client.post(
        "/api/v1/calendar/events",
        json={
            **_event(
                team_id,
                season_id,
                event_type="CHAMPIONSHIP",
                starts_at="2026-11-20T00:00:00-03:00",
                ends_at="2026-11-23T00:00:00-03:00",
            ),
            "title": "BIFE",
            "is_countdown_target": True,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert bife.status_code == 201, bife.text

    payload = client.get(
        f"/api/v1/calendar?team_id={team_id}&season_id={season_id}"
    ).json()
    assert payload["countdown"] == {
        "event_id": bife.json()["id"],
        "title": "BIFE",
        "starts_at": "2026-11-20T03:00:00+00:00",
        "total_trainings": 2,
    }
    counted = [item["countdown"] for item in payload["items"] if item.get("countdown")]
    assert counted == [
        {"target_event_id": bife.json()["id"], "position": 1, "total_trainings": 2, "remaining_trainings": 2},
        {"target_event_id": bife.json()["id"], "position": 2, "total_trainings": 2, "remaining_trainings": 1},
    ]

    second_target = client.post(
        "/api/v1/calendar/events",
        json={
            **_event(
                team_id,
                season_id,
                event_type="CHAMPIONSHIP",
                starts_at="2026-12-01T00:00:00-03:00",
                ends_at="2026-12-02T00:00:00-03:00",
            ),
            "is_countdown_target": True,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert second_target.status_code == 400


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


def test_calendar_reads_the_selected_season_id_and_keeps_the_active_label(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    created = client.post(
        "/api/v1/calendar/events",
        json=_event(
            team_id,
            season_id,
            starts_at="2027-07-28T19:30:00-03:00",
            ends_at="2027-07-28T21:30:00-03:00",
        ),
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201

    selected = client.get(
        f"/api/v1/calendar?team_id={team_id}&season_id={season_id}"
    )
    assert selected.status_code == 200
    payload = selected.json()
    assert payload["season_id"] == season_id
    assert payload["season_label"] == "2026.2"
    assert [item["id"] for item in payload["groups"]["future"]] == [
        created.json()["id"]
    ]


def test_calendar_client_uses_season_id_and_preserves_success_feedback() -> None:
    source = (Path(__file__).parents[1] / "static" / "calendar.js").read_text(
        encoding="utf-8"
    )
    assert "season_id: seasonSelect.value" in source
    assert "Evento criado (ID ${saved.id})." in source
    assert "async function loadCalendar()" in source
    assert "sessionStorage.setItem(cacheKey(\"snapshot\")" in source
    assert "renderAttendanceBriefing(event, records)" in source
    assert "finishTraining(event)" in source
    assert "Encerrar chamada e concluir" in source
    assert "Idempotency-Key" in source
    assert "Salvar mesmo assim" in source


def test_attendance_is_opened_only_from_calendar_training_and_is_idempotent(
    tmp_path: Path,
) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    first = client.post(
        "/api/v1/calendar/events",
        json=_event(
            team_id, season_id,
            starts_at="2026-07-28T19:30:00-03:00",
            ends_at="2026-07-28T21:30:00-03:00",
        ),
        headers={"X-CSRF-Token": csrf},
    ).json()
    second = client.post(
        "/api/v1/calendar/events",
        json=_event(
            team_id, season_id,
            starts_at="2026-07-28T22:00:00-03:00",
            ends_at="2026-07-28T23:00:00-03:00",
        ),
        headers={"X-CSRF-Token": csrf},
    ).json()
    assert client.get("/api/v1/session", params={"training_date": "2026-07-28"}).status_code == 410
    listed = client.get("/api/v1/attendance/trainings", params={"season_id": season_id})
    assert {item["id"] for item in listed.json()["items"]} == {first["id"], second["id"]}

    first_open = client.post(
        f"/api/v1/attendance/trainings/{first['id']}/session",
        headers={"X-CSRF-Token": csrf},
    )
    assert first_open.status_code == 200
    first_session = first_open.json()["session"]["id"]
    assert client.post(
        f"/api/v1/attendance/trainings/{first['id']}/session",
        headers={"X-CSRF-Token": csrf},
    ).json()["session"]["id"] == first_session
    confirmed = client.post(
        f"/api/v1/calendar/events/{first['id']}/confirm",
        json={"base_version": first["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200
    calendar_after_confirmation = client.get(
        "/api/v1/calendar", params={"team_id": team_id, "season_id": season_id}
    )
    confirmed_item = next(
        item
        for item in calendar_after_confirmation.json()["items"]
        if item["id"] == first["id"]
    )
    assert confirmed_item["can_finalize_attendance"] is True
    assert "finish_training" in confirmed_item["available_actions"]
    prematurely_completed = client.post(
        f"/api/v1/calendar/events/{first['id']}/complete",
        json={"base_version": confirmed.json()["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert prematurely_completed.status_code == 409
    assert prematurely_completed.json()["detail"]["code"] == "calendar.attendance_open"
    finalized = client.post(
        f"/api/v1/sessions/{first_session}/finalize",
        headers={"X-CSRF-Token": csrf},
    )
    assert finalized.status_code == 200
    completed = client.post(
        f"/api/v1/calendar/events/{first['id']}/complete",
        json={"base_version": confirmed.json()["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert completed.status_code == 200
    second_session = client.post(
        f"/api/v1/attendance/trainings/{second['id']}/session",
        headers={"X-CSRF-Token": csrf},
    ).json()["session"]["id"]
    assert second_session != first_session
    calendar = client.get(
        "/api/v1/calendar", params={"team_id": team_id, "season_id": season_id}
    )
    assert calendar.status_code == 200
    attendance_capabilities = {
        item["id"]: item["can_view_attendance"] for item in calendar.json()["items"]
    }
    assert attendance_capabilities == {first["id"]: True, second["id"]: True}
    payload = client.get(f"/api/v1/sessions/{first_session}")
    assert payload.status_code == 200
    assert payload.json()["calendar_event"]["id"] == first["id"]
    with manager.read_only_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM training_sessions").fetchone()[0] == 2


def test_player_sees_team_events_and_only_writes_own_justification(
    tmp_path: Path,
) -> None:
    client, manager, data = make_v2(tmp_path)
    ct_csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    training = client.post(
        "/api/v1/calendar/events",
        json=_event(team_id, season_id, is_player_visible=True),
        headers={"X-CSRF-Token": ct_csrf},
    ).json()
    championship = client.post(
        "/api/v1/calendar/events",
        json=_event(
            team_id,
            season_id,
            event_type="CHAMPIONSHIP",
            is_player_visible=True,
        ),
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


def test_calendar_v7_theme_idempotency_conflicts_filters_and_problem_details(
    tmp_path: Path,
) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    options = client.get("/api/v1/calendar/options").json()
    theme = options["teams"][0]["visual_identity"]
    assert theme["slug"] == "hm-ime"
    assert theme["primary"] == "#D71920"
    assert theme["monogram"] == "HM"
    assert theme["logo_url"] == "/static/hm-ime-logo.jpg"

    body = {
        **_event(team_id, season_id),
        "title": "Treino tático",
    }
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "calendar-operation-1"}
    first = client.post("/api/v1/calendar/events", json=body, headers=headers)
    repeated = client.post("/api/v1/calendar/events", json=body, headers=headers)
    assert first.status_code == repeated.status_code == 201
    assert repeated.json()["id"] == first.json()["id"]
    assert repeated.json()["title"] == "Treino tático"
    with manager.read_only_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM calendar_events WHERE title='Treino tático'"
        ).fetchone()[0] == 1

    changed = client.post(
        "/api/v1/calendar/events",
        json={**body, "title": "Outro treino"},
        headers=headers,
    )
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "calendar.idempotency_conflict"

    overlap = client.post(
        "/api/v1/calendar/events/check",
        json={
            "team_id": team_id,
            "starts_at": body["starts_at"],
            "ends_at": body["ends_at"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert overlap.status_code == 200
    assert overlap.json()["has_conflicts"] is True
    assert overlap.json()["items"][0]["id"] == first.json()["id"]

    filtered = client.get(
        "/api/v1/calendar",
        params={
            "team_id": team_id,
            "season_id": season_id,
            "event_type": "TRAINING",
            "status": "PLANNED",
            "q": "tático",
        },
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [first.json()["id"]]
    item = filtered.json()["items"][0]
    assert item["display_title"] == "Treino tático"
    assert item["primary_action"] == "confirm"
    assert {"confirm", "edit", "cancel"} <= set(item["available_actions"])
    assert item["can_view_attendance"] is False

    invalid = client.post(
        "/api/v1/calendar/events",
        json={**body, "ends_at": body["starts_at"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert invalid.status_code == 422
    problem = invalid.json()["detail"]
    assert problem["code"] == "calendar.validation"
    assert problem["suggestion"]
    assert problem["request_id"]


def test_calendar_v7_lifecycle_is_reversible_versioned_and_has_history(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    created = client.post(
        "/api/v1/calendar/events",
        json={**_event(team_id, season_id), "title": "Treino de transição"},
        headers={"X-CSRF-Token": csrf},
    ).json()
    assert created["version"] == 1

    confirmed = client.post(
        f"/api/v1/calendar/events/{created['id']}/confirm",
        json={"reason": "", "base_version": 1},
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "CONFIRMED"
    assert confirmed.json()["version"] == 2

    stale = client.post(
        f"/api/v1/calendar/events/{created['id']}/complete",
        json={"reason": "", "base_version": 1},
        headers={"X-CSRF-Token": csrf},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "calendar.stale_event"

    missing_reason = client.post(
        f"/api/v1/calendar/events/{created['id']}/cancel",
        json={"reason": "", "base_version": 2},
        headers={"X-CSRF-Token": csrf},
    )
    assert missing_reason.status_code == 400
    assert missing_reason.json()["detail"]["code"] == "calendar.cancel_reason_required"

    cancelled = client.post(
        f"/api/v1/calendar/events/{created['id']}/cancel",
        json={"reason": "Quadra interditada", "base_version": 2},
        headers={"X-CSRF-Token": csrf},
    ).json()
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] == 3

    restored = client.post(
        f"/api/v1/calendar/events/{created['id']}/undo-cancel",
        json={"reason": "", "base_version": 3},
        headers={"X-CSRF-Token": csrf},
    ).json()
    assert restored["status"] == "CONFIRMED"
    assert restored["version"] == 4

    rescheduled = client.post(
        f"/api/v1/calendar/events/{created['id']}/reschedule",
        json={
            "starts_at": "2035-08-08T19:00:00-03:00",
            "ends_at": "2035-08-08T21:00:00-03:00",
            "reason": "Ajuste de quadra",
            "base_version": 4,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert rescheduled.status_code == 200
    assert rescheduled.json()["event"]["status"] == "RESCHEDULED"
    assert rescheduled.json()["replacement"]["status"] == "PLANNED"
    assert rescheduled.json()["replacement"]["id"] != created["id"]

    history = client.get(
        f"/api/v1/calendar/events/{created['id']}/history"
    )
    assert history.status_code == 200
    assert [item["action"] for item in history.json()["items"]] == [
        "CREATE",
        "CONFIRM",
        "CANCEL",
        "UNDO_CANCEL",
        "RESCHEDULE",
    ]
    assert client.delete(
        f"/api/v1/calendar/events/{created['id']}",
        headers={"X-CSRF-Token": csrf},
    ).status_code == 405


def test_calendar_v7_recurring_series_previews_and_creates_transactionally(
    tmp_path: Path,
) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    starts_on = "2035-09-03"
    payload = {
        "team_id": team_id,
        "season_id": season_id,
        "event_type": "TRAINING",
        "title": "Treino recorrente",
        "opponent": "",
        "starts_on": starts_on,
        "ends_on": "2035-09-17",
        "start_time": "19:30:00",
        "duration_minutes": 120,
        "weekdays": [date.fromisoformat(starts_on).weekday()],
        "location": "CEPEUSP",
        "notes": "",
        "restriction_kind": None,
    }
    preview = client.post(
        "/api/v1/calendar/series/preview",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200
    assert preview.json()["count"] == 3
    assert preview.json()["conflicts"] == []

    created = client.post(
        "/api/v1/calendar/series",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    assert created.json()["count"] == 3
    assert created.json()["items"][0]["series_id"] == created.json()["series_id"]
    with manager.read_only_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM calendar_event_series"
        ).fetchone()[0] == 1

    anchor = created.json()["items"][1]
    edited = client.put(
        f"/api/v1/calendar/series/{created.json()['series_id']}",
        json={
            **_event(
                team_id,
                season_id,
                starts_at="2035-09-10T20:00:00-03:00",
                ends_at="2035-09-10T21:30:00-03:00",
            ),
            "title": "Treino recorrente ajustado",
            "version": anchor["version"],
            "scope": "FUTURE",
            "anchor_event_id": anchor["id"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["count"] == 2
    with manager.read_only_connection() as connection:
        occurrences = connection.execute(
            """SELECT title,starts_at FROM calendar_events
               WHERE series_id=? ORDER BY starts_at""",
            (created.json()["series_id"],),
        ).fetchall()
    assert occurrences[0]["title"] == "Treino recorrente"
    assert [row["title"] for row in occurrences[1:]] == [
        "Treino recorrente ajustado",
        "Treino recorrente ajustado",
    ]
    assert all("23:00:00+00:00" in row["starts_at"] for row in occurrences[1:])

    date_shift = client.put(
        f"/api/v1/calendar/series/{created.json()['series_id']}",
        json={
            **_event(
                team_id,
                season_id,
                starts_at="2035-09-11T20:00:00-03:00",
                ends_at="2035-09-11T21:30:00-03:00",
            ),
            "title": "Mudança inválida",
            "version": edited.json()["items"][0]["version"],
            "scope": "FUTURE",
            "anchor_event_id": anchor["id"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert date_shift.status_code == 400
    assert date_shift.json()["detail"]["code"] == "calendar.series_date_shift"

    conflicting = client.post(
        "/api/v1/calendar/series",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"]["code"] == "calendar.series_conflict"


def test_player_calendar_exposes_response_only_for_next_training(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    events = []
    for starts_at, ends_at in [
        ("2035-10-01T19:00:00-03:00", "2035-10-01T21:00:00-03:00"),
        ("2035-10-03T19:00:00-03:00", "2035-10-03T21:00:00-03:00"),
    ]:
        events.append(
            client.post(
                "/api/v1/calendar/events",
                json=_event(
                    team_id,
                    season_id,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    is_player_visible=True,
                ),
                headers={"X-CSRF-Token": csrf},
            ).json()
        )
    logout(client)
    login(client, "player", data["passwords"]["player"])
    listed = client.get(
        "/api/v1/calendar",
        params={"team_id": team_id, "season_id": season_id},
    ).json()["items"]
    assert [item["id"] for item in listed] == [item["id"] for item in events]
    assert listed[0]["is_next_player_training"] is True
    assert listed[0]["primary_action"] == "respond"
    assert "respond" in listed[0]["available_actions"]
    assert listed[1]["is_next_player_training"] is False
    assert "respond" not in listed[1]["available_actions"]


def test_calendar_is_private_by_default_and_publication_is_scoped(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    ct_csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, season_id = _options(client)
    private_event = client.post(
        "/api/v1/calendar/events",
        json=_event(team_id, season_id),
        headers={"X-CSRF-Token": ct_csrf},
    )
    assert private_event.status_code == 201, private_event.text
    private_payload = private_event.json()
    assert private_payload["is_player_visible"] == 0

    logout(client)
    login(client, "player", data["passwords"]["player"])
    assert client.get("/api/v1/calendar").json()["items"] == []

    logout(client)
    dev_csrf = login(client, "dev", data["passwords"]["dev"])
    published = client.put(
        f"/api/v1/calendar/events/{private_payload['id']}/player-visibility",
        json={"is_player_visible": True, "base_version": private_payload["version"]},
        headers={"X-CSRF-Token": dev_csrf},
    )
    assert published.status_code == 200, published.text
    assert published.json()["is_player_visible"] == 1

    logout(client)
    login(client, "player", data["passwords"]["player"])
    visible = client.get("/api/v1/calendar").json()["items"]
    assert [item["id"] for item in visible] == [private_payload["id"]]


def test_calendar_page_has_modern_touch_journey_without_hard_delete(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    page = client.get("/app/calendario")
    assert page.status_code == 200
    assert "calendar-brand-mark has-image" in page.text
    styles = client.get("/static/styles.css")
    assert styles.status_code == 200
    assert 'url("/static/hm-ime-logo.jpg")' in styles.text
    for identifier in (
        "calendar-new-event",
        "calendar-agenda-view",
        "calendar-month-view",
        "calendar-editor-dialog",
        "calendar-series-dialog",
        "calendar-detail-dialog",
        "calendar-problem-dialog",
        "calendar-mobile-create",
    ):
        assert f'id="{identifier}"' in page.text
    assert "Excluir evento" not in page.text
    assert 'viewport-fit=cover' in page.text
