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


def test_sql_explorer_is_default_deny_for_player_and_dev(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "player", data["passwords"]["player"])
    assert client.get("/app/consultas").status_code == 403
    assert client.get("/api/v1/sql/catalog").status_code == 403
