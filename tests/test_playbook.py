from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from handball.database import DatabaseManager
from handball.database.migrations import (
    DatabaseMigrator,
    MIGRATION_V8_CHECKSUM,
    MIGRATION_V10_CHECKSUM,
)
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
    is_player_visible: bool = False,
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
            "is_player_visible": is_player_visible,
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

    assert status.current_version == 12
    assert status.latest_version == 12
    assert status.compatible is True
    with manager.read_only_connection() as connection:
        row = connection.execute(
            "SELECT name,checksum_sha256 FROM schema_migrations WHERE version=8"
        ).fetchone()
        v10_row = connection.execute(
            "SELECT name,checksum_sha256 FROM schema_migrations WHERE version=10"
        ).fetchone()
        tables = {
            item[0]
            for item in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            )
        }
    assert tuple(row) == ("playbook_library_and_training_plans", MIGRATION_V8_CHECKSUM)
    assert tuple(v10_row) == (
        "playbook_independent_plans_and_player_calendar_visibility",
        MIGRATION_V10_CHECKSUM,
    )
    assert {
        "playbook_folders",
        "playbook_contents",
        "playbook_content_revisions",
        "playbook_training_plans",
        "playbook_training_plan_revisions",
        "playbook_series",
        "playbook_sessions",
        "playbook_session_event_links",
        "playbook_session_event_history",
        "playbook_session_evaluations",
        "playbook_exercise_specs",
    } <= tables


def test_published_exercise_keeps_structured_participant_requirements(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, folder_id, _ = _seed_and_content(client, csrf)
    payload = _content_payload(team_id, folder_id, title="2x1 na ponta")
    payload.update({
        "content_kind": "EXERCISE",
        "exercise_variants": [{
            "label": "Lado direito",
            "roles": [
                {"group": "ATTACK", "label": "Ponta", "count": 1, "attack_positions": ["PD"]},
                {"group": "ATTACK", "label": "Meia", "count": 1, "attack_positions": ["MD"]},
                {"group": "DEFENSE", "label": "1º marcador", "count": 1, "defensive_positions": ["M1"]},
            ],
        }],
    })
    created = client.post(
        "/api/v1/playbook/contents", json=payload, headers={"X-CSRF-Token": csrf}
    )
    assert created.status_code == 201, created.text
    content_id = int(created.json()["id"])
    assert created.json()["exercise_variants"][0]["roles"][2]["defensive_positions"] == ["M1"]
    published = client.post(
        f"/api/v1/playbook/contents/{content_id}/publish", headers={"X-CSRF-Token": csrf}
    )
    assert published.status_code == 200, published.text
    with manager.unit_of_work(read_only=True) as unit_of_work:
        specs = unit_of_work.playbook.list_published_exercise_specs([team_id])
    exercise = next(item for item in specs if item["content_id"] == content_id)
    assert exercise["title"] == "2x1 na ponta"
    assert exercise["variants"][0]["label"] == "Lado direito"


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
    finish_saved = client.put(
        f"/api/v1/playbook/events/{finish_event_id}/plan",
        json={"title": "Treino de fechamento", "notes": "", "items": [{"content_id": content_id, "sort_order": 0, "planned_minutes": 20, "notes": ""}]},
        headers={"X-CSRF-Token": csrf},
    )
    assert finish_saved.status_code == 200, finish_saved.text
    finish_session_id = int(finish_saved.json()["sessions"][0]["session"]["id"])
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
            "playbook_session_id": finish_session_id,
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
        "session_id": finish_session_id,
        "title": "Cruzamento curto",
    }]
    with manager.read_only_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM playbook_session_evaluations WHERE calendar_event_id=?",
            (finish_event_id,),
        ).fetchone()[0] == 1


def test_independent_plan_series_sessions_links_revisions_and_player_visibility(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, _, content = _seed_and_content(client, csrf)
    content_id = int(content["id"])
    assert client.post(
        f"/api/v1/playbook/contents/{content_id}/publish",
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200
    _, season_id = _team_and_season(client)
    plan_payload = {
        "team_id": team_id,
        "title": "Plano independente",
        "seasonal_objective": "Treinar continuidade de ataque.",
        "context_adjustment": "Sem depender de evento do calendário.",
        "notes": "Versão inicial.",
        "change_summary": "Criação do plano independente.",
        "items": [{
            "content_id": content_id,
            "sort_order": 2,
            "planned_minutes": 30,
            "notes": "Bloco principal.",
        }],
    }
    created_plan = client.post(
        "/api/v1/playbook/plans",
        json=plan_payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert created_plan.status_code == 201, created_plan.text
    plan = created_plan.json()
    plan_id = int(plan["plan"]["id"])
    initial_plan_revision_id = int(plan["revisions"][0]["id"])
    assert plan["items"][0]["sort_order"] == 2
    assert client.get("/api/v1/playbook/plans").json()["items"][0]["id"] == plan_id

    changed_plan = client.put(
        f"/api/v1/playbook/plans/{plan_id}",
        json={**plan_payload, "title": "Plano independente revisado", "notes": "Versão alterada."},
        headers={"X-CSRF-Token": csrf},
    )
    assert changed_plan.status_code == 200, changed_plan.text
    restored_plan = client.post(
        f"/api/v1/playbook/plans/{plan_id}/revisions/{initial_plan_revision_id}/restore",
        headers={"X-CSRF-Token": csrf},
    )
    assert restored_plan.status_code == 200, restored_plan.text
    assert restored_plan.json()["plan"]["title"] == "Plano independente"

    created_series = client.post(
        "/api/v1/playbook/series",
        json={
            "team_id": team_id,
            "plan_id": plan_id,
            "title": "Ciclo de cruzamentos",
            "recurrence_rule": "FREQ=WEEKLY;BYDAY=MO",
            "starts_on": "2035-10-01",
            "ends_on": "2035-11-30",
            "notes": "Série reutilizável.",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created_series.status_code == 201, created_series.text
    series_id = int(created_series.json()["id"])
    assert client.get("/api/v1/playbook/series").json()["items"][0]["id"] == series_id
    empty_sessions = client.get(f"/api/v1/playbook/sessions?team_id={team_id}")
    assert empty_sessions.status_code == 200, empty_sessions.text
    assert empty_sessions.json() == {"items": []}

    unlinked_session = client.post(
        "/api/v1/playbook/sessions",
        json={
            "team_id": team_id,
            "plan_id": plan_id,
            "series_id": series_id,
            "title_override": "Sessão sem evento",
            "local_overrides": {"quadra": "anexo", "minutos": 75},
            "change_summary": "Planejamento sem calendário.",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert unlinked_session.status_code == 201, unlinked_session.text
    unlinked = unlinked_session.json()
    unlinked_id = int(unlinked["session"]["id"])
    first_session_revision_id = int(unlinked["revisions"][0]["id"])
    assert unlinked["event_links"] == []
    executed = client.post(
        f"/api/v1/playbook/sessions/{unlinked_id}/execute",
        json={"execution_status": "COMPLETED", "execution_notes": "Executada sem evento.", "change_summary": "Execução independente."},
        headers={"X-CSRF-Token": csrf},
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["session"]["execution_status"] == "COMPLETED"
    restored_session = client.post(
        f"/api/v1/playbook/sessions/{unlinked_id}/revisions/{first_session_revision_id}/restore",
        headers={"X-CSRF-Token": csrf},
    )
    assert restored_session.status_code == 200, restored_session.text
    assert restored_session.json()["session"]["execution_status"] == "NOT_STARTED"
    assert restored_session.json()["session"]["local_overrides"] == {"minutos": 75, "quadra": "anexo"}
    independent_evaluation = client.post(
        f"/api/v1/playbook/sessions/{unlinked_id}/evaluations",
        json={
            "evaluations": [{
                "content_id": content_id,
                "mastery_stage": "REFINING",
                "continuity_decision": "CONTINUE",
                "notes": "Avaliação sem evento de calendário.",
            }],
            "change_summary": "Avaliação independente.",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert independent_evaluation.status_code == 200, independent_evaluation.text
    assert independent_evaluation.json()["items"] == [{
        "content_id": content_id,
        "mastery_stage": "REFINING",
        "continuity_decision": "CONTINUE",
        "notes": "Avaliação sem evento de calendário.",
        "evaluated_at": independent_evaluation.json()["items"][0]["evaluated_at"],
        "session_id": unlinked_id,
        "calendar_event_id": None,
    }]

    private_event = _create_training(
        client,
        csrf,
        team_id,
        season_id,
        starts_at="2035-10-02T19:00:00-03:00",
        ends_at="2035-10-02T21:00:00-03:00",
    )
    source_event = _create_training(
        client,
        csrf,
        team_id,
        season_id,
        starts_at="2035-10-04T19:00:00-03:00",
        ends_at="2035-10-04T21:00:00-03:00",
        is_player_visible=True,
    )
    source_event_id = int(source_event["id"])
    first_link = client.post(
        f"/api/v1/playbook/sessions/{unlinked_id}/calendar-link",
        json={"event_id": source_event_id, "reason": "Primeiro bloco."},
        headers={"X-CSRF-Token": csrf},
    )
    assert first_link.status_code == 200, first_link.text
    second_session = client.post(
        "/api/v1/playbook/sessions",
        json={
            "team_id": team_id,
            "plan_id": plan_id,
            "series_id": series_id,
            "title_override": "Segundo bloco do mesmo treino",
            "change_summary": "Sessão adicional.",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert second_session.status_code == 201, second_session.text
    second_session_id = int(second_session.json()["session"]["id"])
    assert client.post(
        f"/api/v1/playbook/sessions/{second_session_id}/calendar-link",
        json={"event_id": source_event_id, "reason": "Segundo bloco."},
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200
    before_reschedule = client.get(f"/api/v1/playbook/events/{source_event_id}/plan")
    assert before_reschedule.status_code == 200, before_reschedule.text
    assert [item["session"]["id"] for item in before_reschedule.json()["sessions"]] == [
        unlinked_id,
        second_session_id,
    ]

    rescheduled = client.post(
        f"/api/v1/calendar/events/{source_event_id}/reschedule",
        json={
            "starts_at": "2035-10-05T19:00:00-03:00",
            "ends_at": "2035-10-05T21:00:00-03:00",
            "reason": "Quadra em manutenção.",
            "base_version": source_event["version"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert rescheduled.status_code == 200, rescheduled.text
    replacement = rescheduled.json()["replacement"]
    replacement_id = int(replacement["id"])
    assert replacement["is_player_visible"] == 1
    after_reschedule = client.get(f"/api/v1/playbook/events/{replacement_id}/plan")
    assert after_reschedule.status_code == 200, after_reschedule.text
    assert [item["session"]["id"] for item in after_reschedule.json()["sessions"]] == [
        unlinked_id,
        second_session_id,
    ]
    moved_session = client.get(f"/api/v1/playbook/sessions/{unlinked_id}").json()
    assert moved_session["event_links"][0]["calendar_event_id"] == replacement_id
    assert moved_session["event_links"][0]["link_state"] == "ACTIVE"
    assert any(
        item["action"] == "RESCHEDULE"
        and item["from_event_id"] == source_event_id
        and item["to_event_id"] == replacement_id
        for item in moved_session["history"]
    )

    logout(client)
    player_csrf = login(client, "player", data["passwords"]["player"])
    player_library = client.get(f"/api/v1/playbook?team_id={team_id}")
    assert player_library.status_code == 200, player_library.text
    assert player_library.json()["next_training"]["event"]["id"] == replacement_id
    assert client.get(f"/api/v1/playbook/events/{private_event['id']}/plan").status_code == 403
    assert client.get(f"/api/v1/playbook/events/{replacement_id}/plan").status_code == 200
    assert client.post(
        f"/api/v1/playbook/sessions/{unlinked_id}/execute",
        json={"execution_status": "COMPLETED"},
        headers={"X-CSRF-Token": player_csrf},
    ).status_code == 403


def test_player_next_training_plan_exposes_only_published_preparation(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, handball_id, published_content = _seed_and_content(client, csrf)
    published_content_id = int(published_content["id"])
    assert client.post(
        f"/api/v1/playbook/contents/{published_content_id}/publish",
        headers={"X-CSRF-Token": csrf},
    ).status_code == 200
    draft_response = client.post(
        "/api/v1/playbook/contents",
        json=_content_payload(team_id, handball_id, title="Rascunho interno"),
        headers={"X-CSRF-Token": csrf},
    )
    assert draft_response.status_code == 201, draft_response.text
    draft_content = draft_response.json()
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
    saved = client.put(
        f"/api/v1/playbook/events/{event_id}/plan",
        json={
            "title": "Preparação da defesa 6x0",
            "seasonal_objective": "Ler a troca antes do contato.",
            "context_adjustment": "",
            "notes": "",
            "items": [
                {"content_id": published_content_id, "sort_order": 0, "planned_minutes": 15, "notes": "Revisar antes de sair."},
                {"content_id": int(draft_content["id"]), "sort_order": 1, "planned_minutes": 10, "notes": "Não publicar ainda."},
            ],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200, saved.text
    opened = client.post(
        f"/api/v1/attendance/trainings/{event_id}/session",
        headers={"X-CSRF-Token": csrf},
    )
    assert opened.status_code == 200, opened.text

    logout(client)
    player_csrf = login(client, "player", data["passwords"]["player"])
    active = client.post("/api/v1/me/attendance/active", headers={"X-CSRF-Token": player_csrf})
    assert active.status_code == 200, active.text
    assert int(active.json()["item"]["event"]["id"]) == event_id
    plan = client.get(f"/api/v1/playbook/events/{event_id}/plan")
    assert plan.status_code == 200, plan.text
    assert [item["content_id"] for item in plan.json()["items"]] == [published_content_id]
    assert plan.json()["items"][0]["planned_minutes"] == 15
    assert plan.json()["items"][0]["notes"] == "Revisar antes de sair."


def test_content_fit_reports_whether_exercise_closes_with_confirmed_roster(tmp_path: Path) -> None:
    """Filtro "Fecha com os confirmados" (B3 do handoff HM-IME) — orquestração
    pura sobre dado já existente (planner.enumerate_assignments), sem tabela
    ou coluna nova (AGENTS.md regra 13/19)."""
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    team_id, folder_id, _ = _seed_and_content(client, csrf)

    payload = _content_payload(team_id, folder_id, title="2x1 na ponta direita")
    payload.update({
        "content_kind": "EXERCISE",
        "exercise_variants": [{
            "label": "Lado direito",
            "roles": [
                {"group": "ATTACK", "label": "Ponta direita", "count": 1, "attack_positions": ["PD"]},
                {"group": "ATTACK", "label": "Meia direita", "count": 1, "attack_positions": ["MD"]},
                {"group": "DEFENSE", "label": "1º marcador", "count": 1, "defensive_positions": ["M1"]},
            ],
        }],
    })
    created = client.post("/api/v1/playbook/contents", json=payload, headers={"X-CSRF-Token": csrf})
    assert created.status_code == 201, created.text
    content_id = int(created.json()["id"])
    assert client.post(
        f"/api/v1/playbook/contents/{content_id}/publish", headers={"X-CSRF-Token": csrf}
    ).status_code == 200

    def add_member(name: str, position: str, attack: list[str]) -> int:
        response = client.post(
            "/api/v1/members",
            json={"name": name, "position": position, "attack_positions": attack, "defensive_positions": ["M1"]},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200, response.text
        return int(next(item for item in response.json()["items"] if item["name"] == name)["id"])

    # Os três precisam existir ANTES de abrir a chamada: só assim o registro
    # de presença de cada um é provisionado automaticamente (get_or_create).
    ponta_id = add_member("Ponta Teste", "PD", ["PD"])
    meia_id = add_member("Meia Teste", "MD", ["MD"])
    marcador_id = add_member("Marcador Teste", "PV", ["PV"])

    _, season_id = _team_and_season(client)
    training = _create_training(
        client, csrf, team_id, season_id,
        starts_at="2099-05-01T19:00:00-03:00", ends_at="2099-05-01T21:00:00-03:00",
    )
    event_id = int(training["id"])
    opened = client.post(
        f"/api/v1/attendance/trainings/{event_id}/session", headers={"X-CSRF-Token": csrf}
    )
    assert opened.status_code == 200, opened.text
    session_id = int(opened.json()["session"]["id"])

    def confirm(member_id: int) -> None:
        record = next(
            item for item in client.get(f"/api/v1/sessions/{session_id}").json()["records"]
            if int(item["member_id"]) == member_id
        )
        result = client.put(
            f"/api/v1/sessions/{session_id}/records",
            json={"operations": [{
                "operation_id": f"fit-test-{member_id}",
                "member_id": member_id,
                "base_version": int(record["version"]),
                "confirmation_status": "CONFIRMED_EARLY",
                "present": None,
                "notes": "",
            }], "offline": False},
            headers={"X-CSRF-Token": csrf},
        )
        assert result.status_code == 200, result.text

    confirm(ponta_id)
    confirm(meia_id)

    not_closing = client.get(f"/api/v1/playbook/contents/{content_id}/fit?event_id={event_id}")
    assert not_closing.status_code == 200, not_closing.text
    not_closing_variant = not_closing.json()["variants"][0]
    assert not_closing_variant["fits"] is False
    assert "1º marcador" in not_closing_variant["missing_roles"]

    confirm(marcador_id)

    closing = client.get(f"/api/v1/playbook/contents/{content_id}/fit?event_id={event_id}")
    assert closing.status_code == 200, closing.text
    assert closing.json()["confirmed_count"] == 3
    closing_variant = closing.json()["variants"][0]
    assert closing_variant["fits"] is True
    assert closing_variant["fits_with"] == 3

    missing_event = client.get(f"/api/v1/playbook/contents/{content_id}/fit?event_id=999999")
    assert missing_event.status_code == 404

    # O filtro "Fecha com os confirmados" vive só na tela da CT (B3) — não é
    # exposto ao jogador.
    logout(client)
    login(client, "player", data["passwords"]["player"])
    denied = client.get(f"/api/v1/playbook/contents/{content_id}/fit?event_id={event_id}")
    assert denied.status_code == 403
