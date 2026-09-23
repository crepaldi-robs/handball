from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from handball.modules.playbook.play_templates import play_templates
from handball.modules.playbook.schemas import PlayDiagram
from tests.test_playbook import _content_payload, _create_training, _seed_and_content, _team_and_season
from tests.test_users_authorization import login, logout, make_v2


def _diagram(**overrides) -> dict:
    diagram = {
        "court": "HALF",
        "defense_system": None,
        "actors": [
            {"id": "a-c", "side": "ATTACK", "position": "C", "start": {"x": 0, "y": 10}},
            {"id": "a-md", "side": "ATTACK", "position": "MD", "start": {"x": 5, "y": 9}},
            {"id": "d-m2", "side": "DEFENSE", "position": "M2", "start": {"x": 2, "y": 6.5}},
            {"id": "d-gol", "side": "DEFENSE", "position": "GOL", "start": {"x": 0, "y": 1}},
        ],
        "ball": {"holder": "a-c"},
        "steps": [
            {
                "id": "s1",
                "label": "Cruzamento",
                "duration_s": 2,
                "actions": [
                    {"type": "MOVE", "actor": "a-md", "to": {"x": 1, "y": 9}, "via": [{"x": 3, "y": 10.5}]},
                    {"type": "PASS", "actor": "a-c", "target": "a-md", "at": 0.6},
                ],
            },
            {"id": "s2", "label": "Arremesso", "actions": [{"type": "SHOT", "actor": "a-md", "zone": 1, "at": 0.8}]},
        ],
    }
    diagram.update(overrides)
    return diagram


def test_every_template_is_a_valid_play() -> None:
    templates = play_templates()
    assert {item["key"] for item in templates} >= {"posicional-6x0", "posicional-5x1", "cruzamento", "sete-metros"}
    for template in templates:
        PlayDiagram.model_validate(template["diagram"])
    six_zero = next(item for item in templates if item["key"] == "posicional-6x0")["diagram"]
    # Defensoras ficam fora da área de 6 m (raio 6 m a partir das traves).
    for actor in six_zero["actors"]:
        if actor["side"] == "DEFENSE" and actor["position"] != "GOL":
            x, y = actor["start"]["x"], actor["start"]["y"]
            nearest_post = -1.5 if x < 0 else 1.5
            outside = (abs(x) <= 1.5 and y >= 6) or ((x - nearest_post) ** 2 + y**2) ** 0.5 >= 6
            assert outside, actor


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["steps"][0]["actions"].__setitem__(1, {"type": "PASS", "actor": "a-md", "target": "a-c"}), "só quem está com a bola"),
        (lambda d: d["steps"][1]["actions"].append({"type": "PASS", "actor": "a-md", "target": "a-c", "at": 0.9}), "só quem está com a bola"),
        (lambda d: d["actors"].append({"id": "a-c", "side": "ATTACK", "position": "PE", "start": {"x": -8, "y": 2}}), "identificador único"),
        (lambda d: d["actors"][0].__setitem__("start", {"x": 12, "y": 5}), "less than or equal"),
        (lambda d: d["actors"][2].__setitem__("position", "PV"), "não existe para defesa"),
        (lambda d: d["steps"][0]["actions"].append({"type": "MOVE", "actor": "a-md", "to": {"x": 2, "y": 8}}), "uma vez por passo"),
    ],
)
def test_diagram_validation_rejects_impossible_plays(mutate, message) -> None:
    diagram = _diagram()
    mutate(diagram)
    with pytest.raises(ValidationError) as error:
        PlayDiagram.model_validate(diagram)
    assert message in str(error.value)


def _play_content(client, csrf: str, team_id: int, folder_id: int, *, publish: bool) -> int:
    payload = _content_payload(team_id, folder_id, title="Cruzamento C → MD")
    payload["content_kind"] = "JOGADA"
    created = client.post("/api/v1/playbook/contents", json=payload, headers={"X-CSRF-Token": csrf})
    assert created.status_code == 201, created.text
    content_id = int(created.json()["id"])
    if publish:
        assert client.post(f"/api/v1/playbook/contents/{content_id}/publish", headers={"X-CSRF-Token": csrf}).status_code == 200
    return content_id


def test_diagram_revisions_conflicts_permissions_and_training_day(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, folder_id, _ = _seed_and_content(client, csrf)
    play_id = _play_content(client, csrf, team_id, folder_id, publish=True)
    draft_id = _play_content(client, csrf, team_id, folder_id, publish=False)

    assert client.get("/api/v1/playbook/play-templates").status_code == 200
    assert client.get("/app/playbook/jogadas/nova").status_code == 200
    editor = client.get(f"/app/playbook/jogadas/{play_id}")
    assert editor.status_code == 200 and "/static/play-editor.js" in editor.text

    empty = client.get(f"/api/v1/playbook/contents/{play_id}/diagram").json()
    assert empty == {"available": True, "item": None, "revisions": []}

    first = client.put(
        f"/api/v1/playbook/contents/{play_id}/diagram",
        json={"base_revision": None, "diagram": _diagram()},
        headers={"X-CSRF-Token": csrf},
    )
    assert first.status_code == 200, first.text
    assert first.json()["item"]["revision"] == 1

    changed = _diagram()
    changed["steps"][0]["label"] = "Cruzamento rápido"
    second = client.put(
        f"/api/v1/playbook/contents/{play_id}/diagram",
        json={"base_revision": 1, "diagram": changed},
        headers={"X-CSRF-Token": csrf},
    )
    assert second.status_code == 200
    assert second.json()["item"]["revision"] == 2
    assert [item["revision"] for item in second.json()["revisions"]] == [2, 1]

    stale = client.put(
        f"/api/v1/playbook/contents/{play_id}/diagram",
        json={"base_revision": 1, "diagram": _diagram()},
        headers={"X-CSRF-Token": csrf},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "playbook.revision_conflict"
    assert stale.json()["detail"]["current_revision"] == 2

    invalid = _diagram(ball={"holder": "a-md"})
    rejected = client.put(
        f"/api/v1/playbook/contents/{play_id}/diagram",
        json={"base_revision": 2, "diagram": invalid},
        headers={"X-CSRF-Token": csrf},
    )
    assert rejected.status_code == 422

    assert client.put(
        f"/api/v1/playbook/contents/{draft_id}/diagram",
        json={"base_revision": None, "diagram": _diagram()},
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200

    # A jogada entra no treino e as posições dela viram as filas.
    _, season_id = _team_and_season(client)
    training = _create_training(
        client, csrf, team_id, season_id,
        starts_at="2035-11-04T19:00:00-03:00", ends_at="2035-11-04T21:00:00-03:00", is_player_visible=True,
    )
    event_id = int(training["id"])
    assert client.put(
        f"/api/v1/playbook/events/{event_id}/today",
        json={"items": [{"content_id": play_id, "planned_minutes": 15}]},
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200
    opened = client.post(f"/api/v1/attendance/trainings/{event_id}/session", headers={"X-CSRF-Token": csrf})
    block = opened.json()["training_day"]["blocks"][0]
    assert block["kind"] == "PLAY" and block["has_diagram"] is True
    assert [queue["role"] for queue in block["layout"]["queues"]] == ["Meia direita", "Central"]
    assert block["layout"]["defense_rotation"]["roles"] == ["2º marcador"]

    logout(client)
    login(client, "player", data["passwords"]["player"])
    assert client.get("/api/v1/playbook/play-templates").status_code == 403
    assert client.get("/app/playbook/jogadas/nova").status_code == 403
    visible = client.get(f"/api/v1/playbook/contents/{play_id}/diagram")
    assert visible.status_code == 200
    assert visible.json()["item"]["diagram"]["steps"][0]["label"] == "Cruzamento rápido"
    assert visible.json()["revisions"] == []
    assert client.get(f"/api/v1/playbook/contents/{draft_id}/diagram").status_code == 404
    assert client.put(
        f"/api/v1/playbook/contents/{play_id}/diagram",
        json={"base_revision": 2, "diagram": _diagram()},
        headers={"X-CSRF-Token": "x"},
    ).status_code in {401, 403}


def test_database_without_v15_keeps_plays_read_only(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, folder_id, _ = _seed_and_content(client, csrf)
    play_id = _play_content(client, csrf, team_id, folder_id, publish=True)
    with sqlite3.connect(manager.db_path) as connection:
        connection.execute("DROP TABLE playbook_play_diagram_revisions")
        connection.execute("DROP TABLE playbook_play_diagrams")
        connection.execute("DELETE FROM schema_migrations WHERE version=15")
        connection.execute("PRAGMA user_version = 14")

    read = client.get(f"/api/v1/playbook/contents/{play_id}/diagram")
    assert read.status_code == 200
    assert read.json() == {"available": False, "item": None, "revisions": []}
    refused = client.put(
        f"/api/v1/playbook/contents/{play_id}/diagram",
        json={"base_revision": None, "diagram": _diagram()},
        headers={"X-CSRF-Token": csrf},
    )
    assert refused.status_code == 409
    assert "v15" in refused.json()["detail"]["message"]
