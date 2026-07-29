from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from handball.application import create_app
from tests.test_users_authorization import login, make_v2


def test_ct_can_catalog_query_explain_and_export_csv_without_mutation(
    tmp_path: Path,
) -> None:
    client, manager, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    fingerprint_before = manager.logical_fingerprint()

    catalog = client.get("/api/v1/sql/catalog")
    assert catalog.status_code == 200
    relations = {item["name"]: item for item in catalog.json()["relations"]}
    assert "calendar_events" in relations
    assert relations["users"]["restricted"] is False

    query = client.post(
        "/api/v1/sql/query",
        json={"sql": "SELECT id, label FROM seasons ORDER BY id", "page": 1, "page_size": 10},
    )
    assert query.status_code == 200
    assert query.json()["columns"] == ["id", "label"]
    assert query.json()["rows"][0]["label"] == "2026.2"

    explain = client.post(
        "/api/v1/sql/explain",
        json={"sql": "SELECT id, label FROM seasons", "page": 1, "page_size": 10},
    )
    assert explain.status_code == 200
    assert explain.json()["items"]

    exported = client.post(
        "/api/v1/sql/export/csv",
        json={"sql": "SELECT id, label FROM seasons", "page": 1, "page_size": 10},
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "2026.2" in exported.content.decode("utf-8-sig")

    excel = client.post(
        "/api/v1/sql/export/xlsx",
        json={"sql": "SELECT id, label FROM seasons", "page": 1, "page_size": 10},
    )
    assert excel.status_code == 200
    assert excel.content.startswith(b"PK")
    assert manager.logical_fingerprint() == fingerprint_before


def test_sql_explorer_rejects_writes_multiple_statements_and_restricted_data(
    tmp_path: Path,
) -> None:
    client, manager, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    fingerprint_before = manager.logical_fingerprint()
    for sql in (
        "DELETE FROM seasons",
        "SELECT 1; SELECT 2",
        "SELECT password_hash FROM users",
        "WITH removed AS (DELETE FROM seasons RETURNING id) SELECT * FROM removed",
    ):
        response = client.post("/api/v1/sql/query", json={"sql": sql})
        assert response.status_code == 400, response.text
    assert manager.logical_fingerprint() == fingerprint_before


def test_sql_explorer_is_default_deny_for_player(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "player", data["passwords"]["player"])
    assert client.get("/app/consultas").status_code == 403
    assert client.get("/api/v1/sql/catalog").status_code == 403


def test_dev_writes_require_preview_backup_and_single_use_confirmation(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "dev", data["passwords"]["dev"])
    fingerprint_before = manager.logical_fingerprint()

    assert client.get("/app/consultas").status_code == 200
    assert client.get("/api/v1/sql/catalog").status_code == 200

    direct = client.post(
        "/api/v1/sql/query",
        json={"sql": "CREATE TABLE scratch_dev_test (id INTEGER PRIMARY KEY, value TEXT)"},
    )
    assert direct.status_code == 400
    assert manager.logical_fingerprint() == fingerprint_before

    preview = client.post(
        "/api/v1/sql/changes/preview",
        json={"sql": "CREATE TABLE scratch_dev_test (id INTEGER PRIMARY KEY, value TEXT)"},
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200, preview.text
    assert manager.logical_fingerprint() == fingerprint_before
    token = preview.json()["token"]
    create = client.post(
        "/api/v1/sql/changes/execute",
        json={"token": token},
        headers={"X-CSRF-Token": csrf},
    )
    assert create.status_code == 200, create.text
    assert manager.logical_fingerprint() != fingerprint_before
    assert (manager.backup_dir / create.json()["backup_id"]).is_file()
    repeated = client.post(
        "/api/v1/sql/changes/execute",
        json={"token": token},
        headers={"X-CSRF-Token": csrf},
    )
    assert repeated.status_code == 200
    assert repeated.json()["replayed"] is True
    assert repeated.json()["request_id"] == create.json()["request_id"]
    assert repeated.json()["backup_id"] == create.json()["backup_id"]
    with manager.read_only_connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM security_audit_events WHERE request_id=?",
            (create.json()["request_id"],),
        ).fetchone()[0] == 1
    session_cookie = client.cookies.get("handball_session")
    assert session_cookie
    with TestClient(
        create_app(client.app.state.settings, database_manager=manager),
        base_url="https://testserver",
    ) as restarted:
        restarted.cookies.set("handball_session", session_cookie)
        after_restart = restarted.post(
            "/api/v1/sql/changes/execute",
            json={"token": token},
            headers={"X-CSRF-Token": csrf},
        )
        assert after_restart.status_code == 200, after_restart.text
        assert after_restart.json()["replayed"] is True
        assert after_restart.json()["request_id"] == create.json()["request_id"]
        assert after_restart.json()["backup_id"] == create.json()["backup_id"]
    with manager.read_only_connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM security_audit_events WHERE request_id=?",
            (create.json()["request_id"],),
        ).fetchone()[0] == 1

    insert_preview = client.post(
        "/api/v1/sql/changes/preview",
        json={"sql": "INSERT INTO scratch_dev_test (value) VALUES ('a')"},
        headers={"X-CSRF-Token": csrf},
    )
    insert = client.post(
        "/api/v1/sql/changes/execute",
        json={"token": insert_preview.json()["token"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert insert.status_code == 200, insert.text
    assert insert.json()["affected_rows"] == 1

    drop = client.post(
        "/api/v1/sql/changes/preview",
        json={"sql": "DROP TABLE scratch_dev_test"},
        headers={"X-CSRF-Token": csrf},
    )
    assert drop.status_code == 400


def test_dev_still_cannot_touch_restricted_tables_or_engine_commands(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "dev", data["passwords"]["dev"])
    fingerprint_before = manager.logical_fingerprint()

    for sql in (
        "SELECT password_hash FROM users",
        "DELETE FROM users",
        "UPDATE auth_sessions SET token_hash = 'exposed'",
        "UPDATE auth_sessions SET csrf_token = 'exposed'",
        "INSERT INTO auth_sessions(id,user_id,token_hash,csrf_token,credential_version,created_at,expires_at) VALUES('x',1,'secret','secret',1,'2026-01-01','2099-01-01')",
        "DROP TABLE schema_migrations",
        "PRAGMA foreign_keys = OFF",
        "ATTACH DATABASE 'x.db' AS other",
        "VACUUM",
        "CREATE TRIGGER trg AFTER DELETE ON seasons BEGIN SELECT 1; END",
    ):
        response = client.post(
            "/api/v1/sql/changes/preview",
            json={"sql": sql},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 400, f"{sql!r} -> {response.text}"
    assert manager.logical_fingerprint() == fingerprint_before


def test_dev_can_delete_calendar_event_without_exposing_user_secret(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "dev", data["passwords"]["dev"])
    with manager.unit_of_work() as unit_of_work:
        options = unit_of_work.calendar.list_options({1})
        event = unit_of_work.calendar.create_event(
            {
                "team_id": options["teams"][0]["id"],
                "season_id": options["seasons"][0]["id"],
                "event_type": "GAME",
                "status": "PLANNED",
                "starts_at": "2026-09-01T19:00:00-03:00",
                "ends_at": "2026-09-01T20:00:00-03:00",
                "location": "Teste",
                "notes": "",
                "restriction_kind": None,
            },
            actor_user_id=data["dev_id"],
        )
    preview = client.post(
        "/api/v1/sql/changes/preview",
        json={"sql": f"DELETE FROM calendar_events WHERE id={event['id']}"},
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected_rows"] == 1
    executed = client.post(
        "/api/v1/sql/changes/execute",
        json={"token": preview.json()["token"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert executed.status_code == 200, executed.text
    with manager.unit_of_work(read_only=True) as unit_of_work:
        assert unit_of_work.calendar.get_event(int(event["id"]), {1}) is None
    secret = client.post(
        "/api/v1/sql/query",
        json={"sql": "SELECT password_hash FROM users"},
    )
    assert secret.status_code == 400


def test_change_requires_csrf_and_fingerprint_stability(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "dev", data["passwords"]["dev"])
    sql = "CREATE TABLE scratch_conflict (id INTEGER PRIMARY KEY)"
    without_csrf = client.post("/api/v1/sql/changes/preview", json={"sql": sql})
    assert without_csrf.status_code == 403
    preview = client.post(
        "/api/v1/sql/changes/preview",
        json={"sql": sql},
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200
    with manager.unit_of_work() as unit_of_work:
        unit_of_work.identity.audit_event(
            actor_user_id=data["dev_id"],
            action="test.concurrent",
            entity="database",
            target_id=None,
            origin="pytest",
        )
    conflict = client.post(
        "/api/v1/sql/changes/execute",
        json={"token": preview.json()["token"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert conflict.status_code == 409
    with manager.read_only_connection() as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='scratch_conflict'"
        ).fetchone() is None


def test_unique_ddl_and_internal_sqlite_relations_are_not_exposed(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "dev", data["passwords"]["dev"])
    unique_index = client.post(
        "/api/v1/sql/changes/preview",
        json={"sql": "CREATE UNIQUE INDEX ux_calendar_location ON calendar_events(location)"},
        headers={"X-CSRF-Token": csrf},
    )
    assert unique_index.status_code == 400
    preview = client.post(
        "/api/v1/sql/changes/preview",
        json={"sql": "CREATE TABLE scratch_filtered (id INTEGER PRIMARY KEY)"},
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200, preview.text
    assert all(
        not table.casefold().startswith("sqlite_")
        for table in preview.json()["tables"]
    )


def test_ct_keeps_read_only_sql_access_after_dev_gets_full_access(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    fingerprint_before = manager.logical_fingerprint()
    response = client.post("/api/v1/sql/query", json={"sql": "DELETE FROM seasons"})
    assert response.status_code == 400
    assert manager.logical_fingerprint() == fingerprint_before
