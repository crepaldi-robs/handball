from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from handball.application import create_app
from handball.core.config import AppSettings
from handball.database import DatabaseManager
from handball.database.migrations import DatabaseMigrator, logical_fingerprint


def make_client(
    tmp_path: Path,
    *,
    doctor: Callable[[Path], None] | None = None,
) -> tuple[TestClient, DatabaseManager, dict[str, object]]:
    """Ambiente com admin legado (DEV+CT), um usuário PLAYER e banco migrado.

    ``doctor`` permite alterar o arquivo SQLite entre a migração e a criação
    do app — usado para simular um banco que ainda não recebeu a v13.
    """

    database_path = tmp_path / "elenco.db"
    manager = DatabaseManager(database_path, backup_dir=tmp_path / "backups")
    manager.bootstrap()
    admin_hash = PasswordHasher().hash("senha-admin")
    DatabaseMigrator(database_path).apply_pending(
        expected_fingerprint=logical_fingerprint(database_path),
        legacy_admin=("roberto", admin_hash),
        app_version="pytest-elenco",
        origin="pytest",
    )
    passwords = {"roberto": "senha-admin", "player": "senha-player"}
    with manager.unit_of_work() as unit_of_work:
        team_id = int(unit_of_work.identity.list_teams()[0]["id"])
        player = unit_of_work.identity.list_people_and_players()["players"][0]
        unit_of_work.identity.create_user(
            person_id=int(player["id"]),
            username="player",
            password_hash=PasswordHasher().hash(passwords["player"]),
            roles=["PLAYER"],
            linked_player_id=int(player["team_member_id"]),
            team_id=team_id,
            actor_user_id=1,
        )
        unit_of_work.connection.execute(
            "UPDATE users SET must_change_password=0 WHERE username='player'"
        )
    if doctor is not None:
        doctor(database_path)
    settings = AppSettings(
        admin_username="roberto",
        password_hash=admin_hash,
        secret_key="s" * 64,
        config_path=tmp_path / "config.json",
        cookie_secure=False,
        release_id="pytest-elenco",
    )
    client = TestClient(create_app(settings, database_manager=manager))
    return client, manager, {"passwords": passwords, "team_id": team_id}


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    session = client.get("/api/v1/auth/session")
    assert session.status_code == 200
    return str(session.json()["csrf_token"])


def member_ids(client: TestClient) -> dict[str, int]:
    payload = client.get("/api/v1/elenco/members")
    assert payload.status_code == 200
    return {item["name"]: int(item["id"]) for item in payload.json()["items"]}


def start_session(client: TestClient, csrf: str, scope: str, member_id: int, *, rerank: bool = False):
    return client.post(
        "/api/v1/elenco/ranking/sessions",
        json={"scope": scope, "member_id": member_id, "rerank": rerank},
        headers={"X-CSRF-Token": csrf},
    )


def answer(client: TestClient, csrf: str, payload: dict, outcome: str):
    return client.post(
        f"/api/v1/elenco/ranking/sessions/{payload['session_id']}/answers",
        json={
            "reference_member_id": payload["question"]["reference"]["member_id"],
            "outcome": outcome,
        },
        headers={"X-CSRF-Token": csrf},
    )


def line_layers(client: TestClient) -> list[dict]:
    overview = client.get("/api/v1/elenco/layers")
    assert overview.status_code == 200
    return overview.json()["scopes"]["LINE"]["layers"]


def test_page_is_ct_only_and_player_gets_403(tmp_path: Path) -> None:
    client, _, data = make_client(tmp_path)
    login(client, "roberto", data["passwords"]["roberto"])
    page = client.get("/app/elenco")
    assert page.status_code == 200
    assert "Gestão de Elenco" in page.text
    assert 'id="ranking-wizard"' in page.text
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)

    login(client, "player", data["passwords"]["player"])
    assert client.get("/app/elenco").status_code == 403
    assert client.get("/api/v1/elenco/members").status_code == 403
    assert client.get("/api/v1/elenco/layers").status_code == 403


def test_binary_insertion_builds_layers_with_audit_trail(tmp_path: Path) -> None:
    client, manager, data = make_client(tmp_path)
    csrf = login(client, "roberto", data["passwords"]["roberto"])
    ids = member_ids(client)

    overview = client.get("/api/v1/elenco/layers").json()
    assert overview["available"] is True
    pending_names = {item["name"] for item in overview["scopes"]["LINE"]["pending"]}
    assert "Arthur" in pending_names
    assert "Gabigol" not in pending_names  # goleiro puro não entra na linha
    goalkeeper_pending = {item["name"] for item in overview["scopes"]["GOALKEEPER"]["pending"]}
    assert "Gabigol" in goalkeeper_pending and "Arthur" not in goalkeeper_pending

    # 1º atleta: nenhuma pergunta, cria a camada 0.
    first = start_session(client, csrf, "LINE", ids["Arthur"])
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "COMPLETED"
    assert first.json()["result"] == {
        "layer_ordinal": 0,
        "layer_label": "Camada 1",
        "created_new_layer": True,
    }
    assert first.json()["progress"]["asked"] == 0

    # 2º atleta: uma pergunta contra Arthur; "melhor" cria camada acima.
    second = start_session(client, csrf, "LINE", ids["Gabixo"]).json()
    assert second["status"] == "ASKING"
    assert second["question"]["subject"]["name"] == "Gabixo"
    assert second["question"]["reference"]["member_id"] == ids["Arthur"]
    assert "Quem é melhor em quadra" in second["question"]["text"]
    done = answer(client, csrf, second, "BETTER").json()
    assert done["status"] == "COMPLETED"
    assert done["result"]["layer_ordinal"] == 1
    assert done["result"]["created_new_layer"] is True

    # 3º atleta: busca binária — começa pela camada do meio (ordinal 1).
    third = start_session(client, csrf, "LINE", ids["João Alma"]).json()
    assert third["question"]["reference"]["member_id"] == ids["Gabixo"]
    assert third["progress"]["max_questions"] == 2
    step = answer(client, csrf, third, "WORSE").json()
    assert step["status"] == "ASKING"
    assert step["question"]["reference"]["member_id"] == ids["Arthur"]
    merged = answer(client, csrf, step, "EQUAL").json()
    assert merged["status"] == "COMPLETED"
    assert merged["result"]["layer_ordinal"] == 0
    assert merged["result"]["created_new_layer"] is False

    layers = line_layers(client)
    assert [layer["ordinal"] for layer in layers] == [1, 0]
    assert [item["name"] for item in layers[0]["members"]] == ["Gabixo"]
    assert {item["name"] for item in layers[1]["members"]} == {"Arthur", "João Alma"}

    with sqlite3.connect(manager.db_path) as conn:
        conn.row_factory = sqlite3.Row
        comparisons = conn.execute(
            "SELECT subject_member_id,reference_member_id,outcome,question,actor_user_id,answered_at FROM rank_comparisons ORDER BY id"
        ).fetchall()
        audit_actions = {
            str(row[0])
            for row in conn.execute("SELECT DISTINCT action FROM security_audit_events")
        }
    assert [(row["subject_member_id"], row["outcome"]) for row in comparisons] == [
        (ids["Gabixo"], "BETTER"),
        (ids["João Alma"], "WORSE"),
        (ids["João Alma"], "EQUAL"),
    ]
    assert all(row["actor_user_id"] == 1 and row["answered_at"] for row in comparisons)
    assert all("Quem é melhor em quadra" in str(row["question"]) for row in comparisons)
    assert {"ranking.layer.create", "ranking.assign"} <= audit_actions

    # A camada aparece no cadastro e o goleiro tem hierarquia separada.
    goalkeeper = start_session(client, csrf, "GOALKEEPER", ids["Gabigol"]).json()
    assert goalkeeper["status"] == "COMPLETED"
    members = client.get("/api/v1/elenco/members").json()["items"]
    by_name = {item["name"]: item for item in members}
    assert by_name["Gabixo"]["layers"]["LINE"]["label"] == "Camada 2"
    assert by_name["Gabigol"]["layers"]["GOALKEEPER"]["label"] == "Camada 1"


def test_single_active_session_per_scope_and_reference_drift(tmp_path: Path) -> None:
    client, _, data = make_client(tmp_path)
    csrf = login(client, "roberto", data["passwords"]["roberto"])
    ids = member_ids(client)
    assert start_session(client, csrf, "LINE", ids["Arthur"]).status_code == 200
    started = start_session(client, csrf, "LINE", ids["Gabixo"])
    assert started.status_code == 200
    payload = started.json()
    assert payload["status"] == "ASKING"

    blocked = start_session(client, csrf, "LINE", ids["Pedrinho"])
    assert blocked.status_code == 409
    assert "em andamento" in blocked.json()["detail"]

    wrong_reference = client.post(
        f"/api/v1/elenco/ranking/sessions/{payload['session_id']}/answers",
        json={"reference_member_id": ids["Pedrinho"], "outcome": "BETTER"},
        headers={"X-CSRF-Token": csrf},
    )
    assert wrong_reference.status_code == 409
    assert "recomece" in wrong_reference.json()["detail"]

    cancelled = client.delete(
        f"/api/v1/elenco/ranking/sessions/{payload['session_id']}",
        headers={"X-CSRF-Token": csrf},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    # Cancelou: o escopo libera e o atleta volta para a fila.
    overview = client.get("/api/v1/elenco/layers").json()
    assert overview["scopes"]["LINE"]["active_session"] is None
    assert "Gabixo" in {item["name"] for item in overview["scopes"]["LINE"]["pending"]}
    again = start_session(client, csrf, "LINE", ids["Pedrinho"])
    assert again.status_code == 200


def test_rerank_moves_member_and_sole_member_layer_is_compacted(tmp_path: Path) -> None:
    client, _, data = make_client(tmp_path)
    csrf = login(client, "roberto", data["passwords"]["roberto"])
    ids = member_ids(client)
    start_session(client, csrf, "LINE", ids["Arthur"])
    asking = start_session(client, csrf, "LINE", ids["Gabixo"]).json()
    answer(client, csrf, asking, "BETTER")
    asking = start_session(client, csrf, "LINE", ids["João Alma"]).json()
    step = answer(client, csrf, asking, "WORSE").json()
    answer(client, csrf, step, "EQUAL")
    # Estado: camada 1 = [Gabixo]; camada 0 = [Arthur, João Alma].

    fresh_rejected = start_session(client, csrf, "LINE", ids["Arthur"])
    assert fresh_rejected.status_code == 409  # já ranqueado: exige rerank

    rerank = start_session(client, csrf, "LINE", ids["João Alma"], rerank=True).json()
    assert rerank["status"] == "ASKING"
    assert rerank["question"]["reference"]["member_id"] == ids["Gabixo"]
    moved = answer(client, csrf, rerank, "EQUAL").json()
    assert moved["result"]["layer_ordinal"] == 1
    layers = line_layers(client)
    assert {item["name"] for item in layers[0]["members"]} == {"Gabixo", "João Alma"}
    assert [item["name"] for item in layers[1]["members"]] == ["Arthur"]

    # Re-rank do único membro de uma camada: a camada some, os ordinais
    # compactam e o atleta é reinserido do zero.
    rerank_sole = start_session(client, csrf, "LINE", ids["Arthur"], rerank=True).json()
    assert rerank_sole["status"] == "ASKING"
    assert rerank_sole["progress"]["max_questions"] == 1  # sobrou uma camada
    outcome = answer(client, csrf, rerank_sole, "WORSE").json()
    assert outcome["status"] == "COMPLETED"
    assert outcome["result"] == {
        "layer_ordinal": 0,
        "layer_label": "Camada 1",
        "created_new_layer": True,
    }
    layers = line_layers(client)
    assert [layer["ordinal"] for layer in layers] == [1, 0]
    assert {item["name"] for item in layers[0]["members"]} == {"Gabixo", "João Alma"}
    assert [item["name"] for item in layers[1]["members"]] == ["Arthur"]


def test_refinement_requires_layer_membership_and_position(tmp_path: Path) -> None:
    client, _, data = make_client(tmp_path)
    csrf = login(client, "roberto", data["passwords"]["roberto"])
    ids = member_ids(client)
    start_session(client, csrf, "LINE", ids["Gabixo"])  # ME/C
    asking = start_session(client, csrf, "LINE", ids["João Alma"]).json()  # ME
    answer(client, csrf, asking, "EQUAL")
    layers = line_layers(client)
    layer_id = layers[0]["layer_id"]

    saved = client.put(
        f"/api/v1/elenco/layers/{layer_id}/refinements",
        json={"position": "ME", "member_ids": [ids["João Alma"], ids["Gabixo"]]},
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200, saved.text
    refreshed = line_layers(client)[0]
    assert refreshed["refinements"]["ME"] == [ids["João Alma"], ids["Gabixo"]]

    outsider = client.put(
        f"/api/v1/elenco/layers/{layer_id}/refinements",
        json={"position": "ME", "member_ids": [ids["João Alma"], ids["Arthur"]]},
        headers={"X-CSRF-Token": csrf},
    )
    assert outsider.status_code == 400
    wrong_position = client.put(
        f"/api/v1/elenco/layers/{layer_id}/refinements",
        json={"position": "PV", "member_ids": [ids["João Alma"]]},
        headers={"X-CSRF-Token": csrf},
    )
    assert wrong_position.status_code == 400


def test_metrics_aggregate_semester_by_layer_and_starters(tmp_path: Path) -> None:
    client, manager, data = make_client(tmp_path)
    csrf = login(client, "roberto", data["passwords"]["roberto"])
    ids = member_ids(client)
    start_session(client, csrf, "LINE", ids["Arthur"])
    asking = start_session(client, csrf, "LINE", ids["Gabixo"]).json()
    answer(client, csrf, asking, "BETTER")
    start_session(client, csrf, "GOALKEEPER", ids["Gabigol"])

    # Treino finalizado montado direto no SQLite: só Arthur presente.
    now = "2026-08-06T21:30:00-03:00"
    with sqlite3.connect(manager.db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO training_sessions(training_date,notes,is_finalized,created_at,updated_at) VALUES('2026-08-06','',1,?,?)",
            (now, now),
        )
        session_id = int(cursor.lastrowid)
        conn.executemany(
            """INSERT INTO attendance_records(
                   session_id,member_id,confirmation_status,present,notes,version,updated_at
               ) VALUES(?,?,?,?, '',1,?)""",
            [
                (session_id, ids["Arthur"], "CONFIRMED_EARLY", 1, now),
                (session_id, ids["Gabixo"], "CANCELLED_EARLY", 0, now),
            ],
        )

    metrics = client.get("/api/v1/elenco/metrics").json()
    assert metrics["semester"]["label"] == "2026.2"
    assert metrics["semester"]["starts_on"] == "2026-07-01"
    assert metrics["sessions_considered"] == 1
    athletes = {item["name"]: item for item in metrics["athletes"]}
    assert athletes["Arthur"]["presents"] == 1
    assert athletes["Arthur"]["rate"] == 1.0
    assert athletes["Arthur"]["layer_label"] == "Camada 1"
    assert athletes["Gabixo"]["presents"] == 0
    layer_metrics = {
        (item["scope"], item["ordinal"]): item for item in metrics["layers"]
    }
    assert layer_metrics[("LINE", 1)]["records"] == 1
    assert layer_metrics[("LINE", 1)]["rate"] == 0.0
    assert layer_metrics[("LINE", 0)]["rate"] == 1.0

    comparison = metrics["starters_vs_reserves"]
    # Só 3 ranqueados: as camadas de linha não chegam a 6, então todos os
    # ranqueados de linha + o goleiro da camada mais forte são titulares.
    assert set(comparison["starters"]["members"]) == {
        ids["Arthur"], ids["Gabixo"], ids["Gabigol"],
    }
    assert comparison["reserves"]["members"] == []
    assert ids["Pedrinho"] in comparison["unranked"]["members"]
    assert "camadas de linha mais fortes" in comparison["definition"]

    invalid = client.get("/api/v1/elenco/metrics?semester=2026.3")
    assert invalid.status_code == 400


def _strip_v13(database_path: Path) -> None:
    with sqlite3.connect(database_path) as conn:
        for table in (
            "rank_comparisons",
            "rank_sessions",
            "layer_position_refinements",
            "member_layer_assignments",
            "rank_layers",
        ):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("DELETE FROM schema_migrations WHERE version=13")
        conn.execute("PRAGMA user_version = 12")


def test_degraded_database_without_v13_keeps_module_read_only(tmp_path: Path) -> None:
    client, _, data = make_client(tmp_path, doctor=_strip_v13)
    csrf = login(client, "roberto", data["passwords"]["roberto"])

    overview = client.get("/api/v1/elenco/layers")
    assert overview.status_code == 200
    assert overview.json()["available"] is False
    assert overview.json()["scopes"]["LINE"]["layers"] == []
    assert overview.json()["scopes"]["LINE"]["pending"] == []

    members = client.get("/api/v1/elenco/members")
    assert members.status_code == 200
    assert all(item["layers"] == {} for item in members.json()["items"])

    ids = {item["name"]: int(item["id"]) for item in members.json()["items"]}
    refused = start_session(client, csrf, "LINE", ids["Arthur"])
    assert refused.status_code == 503
    assert "hierarquia do elenco" in refused.json()["detail"]

    # O restante do sistema segue funcionando com o banco antigo.
    assert client.get("/api/v1/history").status_code == 200
    assert client.get("/app/presencas").status_code == 200
