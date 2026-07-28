from __future__ import annotations

from pathlib import Path

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
    assert relations["users"]["restricted"] is True

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


def test_dev_has_full_sql_access_including_delete_and_ddl(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    login(client, "dev", data["passwords"]["dev"])
    fingerprint_before = manager.logical_fingerprint()

    assert client.get("/app/consultas").status_code == 200
    assert client.get("/api/v1/sql/catalog").status_code == 200

    create = client.post(
        "/api/v1/sql/query",
        json={"sql": "CREATE TABLE scratch_dev_test (id INTEGER PRIMARY KEY, value TEXT)"},
    )
    assert create.status_code == 200, create.text

    insert = client.post(
        "/api/v1/sql/query",
        json={"sql": "INSERT INTO scratch_dev_test (value) VALUES ('a')"},
    )
    assert insert.status_code == 200, insert.text
    assert insert.json()["affected_rows"] == 1
    assert manager.logical_fingerprint() != fingerprint_before

    update = client.post(
        "/api/v1/sql/query",
        json={"sql": "UPDATE scratch_dev_test SET value = 'b' WHERE id = 1"},
    )
    assert update.status_code == 200, update.text
    assert update.json()["affected_rows"] == 1

    delete = client.post(
        "/api/v1/sql/query",
        json={"sql": "DELETE FROM scratch_dev_test WHERE id = 1"},
    )
    assert delete.status_code == 200, delete.text
    assert delete.json()["affected_rows"] == 1

    drop = client.post("/api/v1/sql/query", json={"sql": "DROP TABLE scratch_dev_test"})
    assert drop.status_code == 200, drop.text
    assert manager.logical_fingerprint() == fingerprint_before


def test_dev_still_cannot_touch_restricted_tables_or_engine_commands(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    login(client, "dev", data["passwords"]["dev"])
    fingerprint_before = manager.logical_fingerprint()

    for sql in (
        "SELECT password_hash FROM users",
        "DELETE FROM users",
        "UPDATE auth_sessions SET revoked_at = NULL",
        "DROP TABLE schema_migrations",
        "PRAGMA foreign_keys = OFF",
        "ATTACH DATABASE 'x.db' AS other",
        "VACUUM",
        "CREATE TRIGGER trg AFTER DELETE ON seasons BEGIN SELECT 1; END",
    ):
        response = client.post("/api/v1/sql/query", json={"sql": sql})
        assert response.status_code == 400, f"{sql!r} -> {response.text}"
    assert manager.logical_fingerprint() == fingerprint_before


def test_ct_keeps_read_only_sql_access_after_dev_gets_full_access(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    fingerprint_before = manager.logical_fingerprint()
    response = client.post("/api/v1/sql/query", json={"sql": "DELETE FROM seasons"})
    assert response.status_code == 400
    assert manager.logical_fingerprint() == fingerprint_before
