from __future__ import annotations

from pathlib import Path

from tests.test_playbook import _content_payload, _create_training, _seed_and_content, _team_and_season
from tests.test_users_authorization import login, logout, make_v2


def _exercise(client, csrf: str, team_id: int, folder_id: int, *, publish: bool = True, title: str = "Cruzamento 2x1") -> int:
    payload = _content_payload(team_id, folder_id, title=title)
    payload.update(
        {
            "content_kind": "EXERCISE",
            "exercise_variants": [
                {
                    "label": "Lado direito",
                    "roles": [
                        {"group": "ATTACK", "label": "Meia direita", "count": 1, "attack_positions": ["MD"]},
                        {"group": "ATTACK", "label": "Ponta direita", "count": 1, "attack_positions": ["PD"]},
                        {"group": "DEFENSE", "label": "1º marcador", "count": 1, "defensive_positions": ["M1"]},
                    ],
                }
            ],
        }
    )
    created = client.post("/api/v1/playbook/contents", json=payload, headers={"X-CSRF-Token": csrf})
    assert created.status_code == 201, created.text
    content_id = int(created.json()["id"])
    if publish:
        assert client.post(f"/api/v1/playbook/contents/{content_id}/publish", headers={"X-CSRF-Token": csrf}).status_code == 200
    return content_id


def _confirm_everyone(client, csrf: str, session_id: int) -> None:
    records = client.get(f"/api/v1/sessions/{session_id}").json()["records"]
    result = client.put(
        f"/api/v1/sessions/{session_id}/records",
        json={
            "operations": [
                {
                    "operation_id": f"today-op-{record['member_id']:04d}",
                    "member_id": int(record["member_id"]),
                    "base_version": int(record["version"]),
                    "confirmation_status": "CONFIRMED_EARLY",
                    "present": None,
                    "notes": "",
                }
                for record in records
            ],
            "offline": False,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert result.status_code == 200, result.text


def test_today_button_builds_route_queues_and_player_sees_only_final_plan(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, folder_id, _ = _seed_and_content(client, csrf)
    exercise_id = _exercise(client, csrf, team_id, folder_id)
    draft_id = _exercise(client, csrf, team_id, folder_id, publish=False, title="Rascunho da CT")
    _, season_id = _team_and_season(client)
    training = _create_training(
        client,
        csrf,
        team_id,
        season_id,
        starts_at="2035-11-04T19:00:00-03:00",
        ends_at="2035-11-04T21:00:00-03:00",
        is_player_visible=True,
    )
    event_id = int(training["id"])

    invalid = client.put(
        f"/api/v1/playbook/events/{event_id}/today",
        json={"items": [{"content_id": exercise_id, "collective": True}]},
        headers={"X-CSRF-Token": csrf},
    )
    assert invalid.status_code == 422

    saved = client.put(
        f"/api/v1/playbook/events/{event_id}/today",
        json={
            "items": [
                {"content_id": exercise_id, "planned_minutes": 20},
                {"content_id": draft_id, "planned_minutes": 10},
                {"collective": True, "planned_minutes": 30},
            ]
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200, saved.text
    titles = [item["title"] for item in saved.json()["items"]]
    assert titles == ["Cruzamento 2x1", "Rascunho da CT", "Coletivo"]
    # O conteúdo "Coletivo" é criado uma vez e reaproveitado.
    again = client.put(
        f"/api/v1/playbook/events/{event_id}/today",
        json={"items": [{"content_id": exercise_id, "planned_minutes": 20}, {"content_id": draft_id, "planned_minutes": 10}, {"collective": True, "planned_minutes": 30}]},
        headers={"X-CSRF-Token": csrf},
    )
    assert [item["content_id"] for item in again.json()["items"]] == [item["content_id"] for item in saved.json()["items"]]

    opened = client.post(f"/api/v1/attendance/trainings/{event_id}/session", headers={"X-CSRF-Token": csrf})
    assert opened.status_code == 200, opened.text
    session_id = int(opened.json()["session"]["id"])
    _confirm_everyone(client, csrf, session_id)
    payload = client.get(f"/api/v1/sessions/{session_id}").json()

    day = payload["training_day"]
    assert [block["kind"] for block in day["blocks"]] == ["EXERCISE", "EXERCISE", "COLLECTIVE"]
    assert [block["starts_at"][11:16] for block in day["blocks"]] == ["19:00", "19:20", "19:30"]
    queues = day["blocks"][0]["layout"]["queues"]
    placed = sorted(member["member_id"] for queue in queues for member in queue["members"])
    goalkeepers = day["blocks"][0]["layout"]["apart"]
    confirmed = {int(record["member_id"]) for record in payload["records"]}
    assert set(placed) | {item["member_id"] for item in goalkeepers} == confirmed
    message = payload["coach_message"]
    assert "1) 19:00–19:20 · Cruzamento 2x1" in message
    assert "3) 19:30–20:00 · Coletivo" in message
    assert "VIABILIDADE" not in message and "RELATÓRIO PRÉ-TREINO" not in message

    logout(client)
    player_csrf = login(client, "player", data["passwords"]["player"])
    del player_csrf
    plan = client.get("/api/v1/me/training-plan")
    assert plan.status_code == 200, plan.text
    item = plan.json()["item"]
    assert [block["title"] for block in item["blocks"]] == ["Cruzamento 2x1", "Coletivo"]
    text = repr(item)
    assert "layer" not in text and "Rascunho" not in text and "alerts" not in text
    assert item["blocks"][0]["layout"]["queues"]
