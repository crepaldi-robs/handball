from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from handball.database import DatabaseManager
from handball.database.migrations import DatabaseMigrator, MIGRATION_V8_CHECKSUM
from tests.test_users_authorization import login, logout, make_v2


def _team_and_season(client: TestClient) -> tuple[int, int]:
    options = client.get("/api/v1/calendar/options")
    assert options.status_code == 200, options.text
    payload = options.json()
    team = payload["teams"][0]
    season = next(item for item in payload["seasons"] if item["team_id"] == team["id"])
    return int(team["id"]), int(season["id"])


def _content_payload(team_id: int, folder_id: int, *, title: str = "Cruzamento curto") -> dict[str, object]:
    return {
        "team_id": team_id,
        "title": title,
        "content_kind": "Jogada",
        "perspective": "ATTACK",
        "objective": "Criar vantagem para o armador em superioridade posicional.",
        "when_to_use": "Contra defesa compacta.",
        "prerequisites": "Passe em velocidade e leitura do pivô.",
        "steps": "1. Armador fixa.\n2. Pivô bloqueia.\n3. Lateral ataca o espaço.",
        "notes": "Manter amplitude antes do cruzamento.",
        "aliases": ["Cruza curto", "X curto"],
        "positions": ["Armador", "Pivô"],
        "placements": [{"folder_id": folder_id, "placement_kind": "PLACEMENT", "sort_order": 0}],
        "change_note": "Primeira versão de teste.",
    }


def _create_training(
    client: TestClient,
    csrf: str,
    team_id: int,
    season_id: int,
    *,
    starts_at: str,
    ends_at: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/calendar/events",
        json={
            "team_id": team_id,
            "season_id": season_id,
            "event_type": "TRAINING",
            "status": "PLANNED",
            "title": "Treino tático",
            "opponent": "",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "location": "CEPEUSP",
            "notes": "Treino planejado pelo Playbook",
            "restriction_kind": None,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_and_content(client: TestClient, csrf: str) -> tuple[int, int, dict[str, object]]:
    team_id, _ = _team_and_season(client)
    seeded = client.post(
        "/api/v1/playbook/taxonomy/seed",
        json={"team_id": team_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert seeded.status_code == 200, seeded.text
    handball = next(item for item in seeded.json()["items"] if item["name"] == "Handball")
    created = client.post(
        "/api/v1/playbook/contents",
        json=_content_payload(team_id, int(handball["id"])),
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201, created.text
    return team_id, int(handball["id"]), created.json()


def test_v8_migration_registers_playbook_contract(tmp_path: Path) -> None:
    _, manager, _ = make_v2(tmp_path)

    status = DatabaseMigrator(manager.db_path).status()

    assert status.current_version == 9
    assert status.latest_version == 9
    assert status.compatible is True
    with manager.read_only_connection() as connection:
        row = connection.execute(
            "SELECT name,checksum_sha256 FROM schema_migrations WHERE version=8"
        ).fetchone()
        tables = {
            item[0]
            for item in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            )
        }
    assert tuple(row) == ("playbook_library_and_training_plans", MIGRATION_V8_CHECKSUM)
    assert {
        "playbook_folders",
        "playbook_contents",
        "playbook_content_revisions",
        "playbook_training_plans",
        "playbook_plan_transfers",
        "playbook_plan_evaluations",
    } <= tables


def test_playbook_library_content_permissions_and_protected_media(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    assert client.get("/app/playbook", follow_redirects=False).status_code == 303
    csrf = login(client, "ct", data["passwords"]["ct"])

    page = client.get("/app/playbook")
    assert page.status_code == 200
    assert "Playbook do time" in page.text
    assert "/static/playbook.js" in page.text
    assert 'href="/app/playbook"' in client.get("/app").text

    team_id, handball_id, draft = _seed_and_content(client, csrf)
    content_id = int(draft["id"])
    library = client.get(f"/api/v1/playbook?team_id={team_id}&q=X%20curto")
    assert library.status_code == 200, library.text
    assert library.json()["teams"][0]["id"] == team_id
    assert any(item["id"] == content_id for item in library.json()["contents"])

    renamed = client.put(
        f"/api/v1/playbook/contents/{content_id}",
        json={**_content_payload(team_id, handball_id, title="Cruzamento curto revisado"), "change_note": "Ajuste de leitura"},
        headers={"X-CSRF-Token": csrf},
    )
    assert renamed.status_code == 200, renamed.text
    revisions = client.get(f"/api/v1/playbook/contents/{content_id}/revisions")
    assert revisions.status_code == 200
    assert [item["revision_number"] for item in revisions.json()["items"]] == [2, 1]

    shortcut_folder = client.post(
        "/api/v1/playbook/folders",
        json={"team_id": team_id, "name": "Atalhos de teste", "parent_id": None},
        headers={"X-CSRF-Token": csrf},
    )
    assert shortcut_folder.status_code == 201, shortcut_folder.text
    moved = client.post(
        "/api/v1/playbook/contents/move",
        json={
            "content_ids": [content_id],
            "folder_id": shortcut_folder.json()["id"],
            "operation": "SHORTCUT",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert moved.status_code == 200, moved.text
    assert {item["placement_kind"] for item in moved.json()["items"][0]["folders"]} == {"PLACEMENT", "SHORTCUT"}

    upload = client.post(
        f"/api/v1/playbook/contents/{content_id}/attachments/upload",
        files={"file": ("diagrama.png", b"\x89PNG\r\n\x1a\nmini", "image/png")},
        data={"label": "Diagrama de cruzamento", "offline_essential": "true"},
        headers={"X-CSRF-Token": csrf},
    )
    assert upload.status_code == 201, upload.text
    attachment_id = int(upload.json()["id"])
    detail = client.get(f"/api/v1/playbook/contents/{content_id}")
    assert detail.status_code == 200
    assert "storage_key" not in detail.json()["attachments"][0]
    assert client.get(f"/api/v1/playbook/attachments/{attachment_id}/download").status_code == 200
    manifest = client.get("/api/v1/playbook/offline")
    assert manifest.status_code == 200
    assert [item["id"] for item in manifest.json()["items"]] == [attachment_id]

    assert client.post(
        f"/api/v1/playbook/contents/{content_id}/publish",
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200
    logout(client)
    player_csrf = login(client, "player", data["passwords"]["player"])
    player_library = client.get(f"/api/v1/playbook?team_id={team_id}")
    assert player_library.status_code == 200
    assert player_library.json()["can_manage"] is False
    assert any(item["id"] == content_id for item in player_library.json()["contents"])
    assert client.post(
        "/api/v1/playbook/folders",
        json={"team_id": team_id, "name": "Não permitido"},
        headers={"X-CSRF-Token": player_csrf},
    ).status_code == 403
    favorite = client.post(
        f"/api/v1/playbook/contents/{content_id}/favorite",
        headers={"X-CSRF-Token": player_csrf},
    )
    assert favorite.status_code == 200 and favorite.json()["favorite"] is True
    assert client.get(f"/api/v1/playbook/contents/{content_id}").status_code == 200
    assert client.post(
        f"/api/v1/playbook/contents/{content_id}/view",
        headers={"X-CSRF-Token": player_csrf},
    ).status_code == 204
    favorites = client.get(f"/api/v1/playbook?team_id={team_id}").json()["favorites"]
    assert [item["id"] for item in favorites] == [content_id]
    recent = client.get(f"/api/v1/playbook?team_id={team_id}").json()["recent"]
    assert [item["id"] for item in recent] == [content_id]
    with manager.read_only_connection() as connection:
        actions = {
            row[0]
            for row in connection.execute(
                "SELECT action FROM security_audit_events WHERE origin='playbook'"
            )
        }
    assert {"playbook.taxonomy.seed", "playbook.content.create", "playbook.content.publish"} <= actions


def test_playbook_plan_transfers_on_reschedule_and_guided_finish(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, handball_id, content = _seed_and_content(client, csrf)
    content_id = int(content["id"])
    assert client.post(
        f"/api/v1/playbook/contents/{content_id}/publish",
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200
    _, season_id = _team_and_season(client)

    source = _create_training(
        client, csrf, team_id, season_id,
        starts_at="2035-09-02T19:00:00-03:00",
        ends_at="2035-09-02T21:00:00-03:00",
    )
    source_id = int(source["id"])
    saved = client.put(
        f"/api/v1/playbook/events/{source_id}/plan",
        json={
            "title": "Contra 6x0",
            "seasonal_objective": "Melhorar a leitura do bloqueio e da troca defensiva.",
            "context_adjustment": "A quadra estará reduzida por evento paralelo.",
            "notes": "Priorizar pivô",
            "items": [{"content_id": content_id, "sort_order": 0, "planned_minutes": 25, "notes": "Bloco inicial"}],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["availability"] is None

    rescheduled = client.post(
        f"/api/v1/calendar/events/{source_id}/reschedule",
        json={
            "starts_at": "2035-09-03T19:00:00-03:00",
            "ends_at": "2035-09-03T21:00:00-03:00",
            "reason": "Quadra indisponível",
            "base_version": source["version"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert rescheduled.status_code == 200, rescheduled.text
    replacement_id = int(rescheduled.json()["replacement"]["id"])
    assert rescheduled.json()["playbook_plan_transfer"] == {
        "plan_id": saved.json()["plan"]["id"],
        "from_event_id": source_id,
        "to_event_id": replacement_id,
    }
    replacement_plan = client.get(f"/api/v1/playbook/events/{replacement_id}/plan")
    assert replacement_plan.status_code == 200, replacement_plan.text
    assert replacement_plan.json()["items"][0]["content_id"] == content_id
    assert replacement_plan.json()["plan"]["seasonal_objective"].startswith("Melhorar")
    assert replacement_plan.json()["plan"]["context_adjustment"].startswith("A quadra")
    assert replacement_plan.json()["transfers"][0]["from_event_id"] == source_id

    finish_event = _create_training(
        client, csrf, team_id, season_id,
        starts_at="2035-09-10T19:00:00-03:00",
        ends_at="2035-09-10T21:00:00-03:00",
    )
    finish_event_id = int(finish_event["id"])
    assert client.put(
        f"/api/v1/playbook/events/{finish_event_id}/plan",
        json={"title": "Treino de fechamento", "notes": "", "items": [{"content_id": content_id, "sort_order": 0, "planned_minutes": 20, "notes": ""}]},
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200
    confirmed = client.post(
        f"/api/v1/calendar/events/{finish_event_id}/confirm",
        json={"reason": "Confirmado para teste", "base_version": finish_event["version"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200, confirmed.text
    opened = client.post(
        f"/api/v1/attendance/trainings/{finish_event_id}/session",
        headers={"X-CSRF-Token": csrf},
    )
    assert opened.status_code == 200, opened.text
    completed = client.post(
        f"/api/v1/playbook/events/{finish_event_id}/finish",
        json={
            "session_notes": "Pivô respondeu bem ao bloqueio.",
            "finalize_attendance": True,
            "evaluations": [{
                "content_id": content_id,
                "mastery_stage": "IMPROVING",
                "continuity_decision": "CONTINUE",
                "notes": "Retomar no próximo treino.",
            }],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["event"]["status"] == "COMPLETED"
    assert completed.json()["session"]["is_finalized"] == 1
    final_plan = client.get(f"/api/v1/playbook/events/{finish_event_id}/plan")
    assert final_plan.status_code == 200
    assert final_plan.json()["evaluations"] == [{
        "content_id": content_id,
        "mastery_stage": "IMPROVING",
        "continuity_decision": "CONTINUE",
        "notes": "Retomar no próximo treino.",
        "evaluated_at": final_plan.json()["evaluations"][0]["evaluated_at"],
        "title": "Cruzamento curto",
    }]
    with manager.read_only_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM playbook_plan_evaluations WHERE calendar_event_id=?",
            (finish_event_id,),
        ).fetchone()[0] == 1
