from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from handball.application import create_app
from handball.core.authorization import Permission, ROLE_PERMISSIONS
from handball.core.config import AppSettings
from handball.database import DatabaseManager
from handball.database.migrations import DatabaseMigrator, logical_fingerprint, verify_database
from handball.database.repositories import attendance as attendance_repository


def make_v2(tmp_path: Path) -> tuple[TestClient, DatabaseManager, dict[str, object]]:
    database_path = tmp_path / "presencas.db"
    manager = DatabaseManager(database_path, backup_dir=tmp_path / "backups")
    manager.bootstrap()
    bob_hash = PasswordHasher().hash("senha-bob")
    before_ids = manager.attendance_repository().list_members()
    DatabaseMigrator(database_path).apply_pending(
        expected_fingerprint=logical_fingerprint(database_path),
        legacy_admin=("bob", bob_hash),
        app_version="pytest-v2",
        origin="pytest",
    )
    passwords = {"bob": "senha-bob", "ct": "senha-ct", "player": "senha-player", "dev": "senha-dev"}
    with manager.unit_of_work() as unit_of_work:
        hm_ime_team_id = int(unit_of_work.identity.list_teams()[0]["id"])
        player = unit_of_work.identity.list_people_and_players()["players"][0]
        player_id = unit_of_work.identity.create_user(
            person_id=int(player["id"]),
            username="player",
            password_hash=PasswordHasher().hash(passwords["player"]),
            roles=["PLAYER"],
            linked_player_id=int(player["team_member_id"]),
            team_id=hm_ime_team_id,
            actor_user_id=1,
        )
        ct_person = unit_of_work.identity.create_person("Comissão Teste", "CT Teste")
        ct_id = unit_of_work.identity.create_user(
            person_id=ct_person,
            username="ct",
            password_hash=PasswordHasher().hash(passwords["ct"]),
            roles=["CT"],
            linked_player_id=None,
            team_id=hm_ime_team_id,
            actor_user_id=1,
        )
        dev_person = unit_of_work.identity.create_person("Dev Teste")
        dev_id = unit_of_work.identity.create_user(
            person_id=dev_person,
            username="dev",
            password_hash=PasswordHasher().hash(passwords["dev"]),
            roles=["DEV"],
            linked_player_id=None,
            actor_user_id=1,
        )
        unit_of_work.connection.execute(
            "UPDATE users SET must_change_password=0 WHERE username IN('ct','player','dev')"
        )
    settings = AppSettings(
        admin_username="bob",
        password_hash=bob_hash,
        secret_key="s" * 64,
        config_path=tmp_path / "config.json",
        release_id="pytest-v2",
    )
    # HTTPS como em producao: o cookie de sessao e Secure por padrao, entao um
    # cliente em http descartaria a sessao silenciosamente.
    client = TestClient(
        create_app(settings, database_manager=manager),
        base_url="https://testserver",
    )
    return client, manager, {
        "passwords": passwords,
        "player_id": player_id,
        "player_member_id": int(player["team_member_id"]),
        "ct_id": ct_id,
        "dev_id": dev_id,
        "before_ids": [int(item["id"]) for item in before_ids],
        "team_id": hm_ime_team_id,
    }


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session = client.get("/api/v1/auth/session")
    assert session.status_code == 200
    return str(session.json()["csrf_token"])


def logout(client: TestClient) -> None:
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)


def test_dev_can_assign_direct_sql_permission_to_player(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "dev", data["passwords"]["dev"])
    granted = client.put(
        f"/api/v1/admin/users/{data['player_id']}/permissions",
        json={"permissions": ["sql.explore"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert granted.status_code == 200, granted.text
    logout(client)
    login(client, "player", data["passwords"]["player"])
    assert client.get("/api/v1/sql/catalog").status_code == 200
    me = client.get("/api/v1/me").json()
    assert "sql.explore" in me["permissions"]


def open_calendar_training(client: TestClient, csrf: str, training_date: str) -> dict[str, object]:
    options = client.get("/api/v1/calendar/options").json()
    team = options["teams"][0]
    season = next(item for item in options["seasons"] if item["label"] == "2026.2")
    created = client.post(
        "/api/v1/calendar/events",
        json={
            "team_id": team["id"], "season_id": season["id"],
            "event_type": "TRAINING", "status": "PLANNED",
            "starts_at": f"{training_date}T19:30:00-03:00",
            "ends_at": f"{training_date}T21:30:00-03:00",
            "location": "CEPEUSP", "notes": "Teste", "restriction_kind": None,
            "is_player_visible": True,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201, created.text
    opened = client.post(
        f"/api/v1/attendance/trainings/{created.json()['id']}/session",
        headers={"X-CSRF-Token": csrf},
    )
    assert opened.status_code == 200, opened.text
    return opened.json()


def test_permission_matrix_is_typed_and_dev_does_not_imply_sport() -> None:
    assert Permission.USERS_MANAGE in ROLE_PERMISSIONS["DEV"]
    assert Permission.ATTENDANCE_READ_TEAM not in ROLE_PERMISSIONS["DEV"]
    assert Permission.ATTENDANCE_WRITE in ROLE_PERMISSIONS["CT"]
    assert ROLE_PERMISSIONS["PLAYER"] == frozenset(
        {
            Permission.ATTENDANCE_READ_SELF,
            Permission.ATTENDANCE_WRITE_SELF,
            Permission.REPORTS_READ_SELF,
            Permission.CALENDAR_READ_TEAM,
            Permission.CALENDAR_JUSTIFICATION_SELF,
            Permission.PLAYBOOK_READ,
        }
    )


def test_v2_migration_preserves_members_and_materializes_bob(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    assert verify_database(manager.db_path)["ok"] is True
    assert DatabaseMigrator(manager.db_path).status().current_version == 13
    assert [int(item["id"]) for item in manager.attendance_repository().list_members()] == data["before_ids"]
    with manager.read_only_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM player_user_links").fetchone()[0] == len(data["before_ids"])
        bob = connection.execute("SELECT username,password_hash FROM users WHERE username='bob'").fetchone()
        roles = {row[0] for row in connection.execute("SELECT role_code FROM system_roles WHERE user_id=1")}
    assert bob is not None and PasswordHasher().verify(bob["password_hash"], "senha-bob")
    assert roles == {"DEV", "CT"}
    assert client.get("/ready").json()["schema_version"] == 13


def test_logins_and_scoped_hub(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "bob", data["passwords"]["bob"])
    assert client.get("/api/v1/admin/users").status_code == 200
    assert client.get("/api/v1/attendance/trainings").status_code == 200
    logout(client)
    login(client, "ct", data["passwords"]["ct"])
    assert client.get("/api/v1/attendance/trainings").status_code == 200
    assert client.get("/api/v1/admin/users").status_code == 403
    logout(client)
    login(client, "player", data["passwords"]["player"])
    hub = client.get("/app")
    assert "Meu relatório" in hub.text and "Administração de usuários" not in hub.text
    assert client.get("/api/v1/me/report").status_code == 200


def test_logout_requires_session_csrf(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "bob", data["passwords"]["bob"])
    assert client.post("/logout", follow_redirects=False).status_code == 403
    assert client.get("/api/v1/me").status_code == 200
    assert client.post(
        "/logout", data={"csrf_token": csrf}, follow_redirects=False
    ).status_code == 303
    assert client.get("/api/v1/me").status_code == 401


def test_player_can_self_register_once_and_enters_hub(tmp_path: Path) -> None:
    client, manager, _ = make_v2(tmp_path)
    with manager.unit_of_work(read_only=True) as unit_of_work:
        available = unit_of_work.identity.available_player_registrations()
    assert available
    response = client.post(
        "/register",
        data={
            "team_member_id": available[0]["id"], "username": "novo-jogador",
            "password": "x", "password_confirmation": "x",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303 and response.headers["location"] == "/app"
    me = client.get("/api/v1/me").json()
    assert me["linked_player_id"] == available[0]["id"]
    assert me["must_change_password"] is False
    second = client.post(
        "/register",
        data={"team_member_id": available[0]["id"], "username": "outro", "password": "x", "password_confirmation": "x"},
    )
    assert second.status_code == 400


def test_signup_wizard_lists_active_teams_without_wearing_their_identity(
    tmp_path: Path,
) -> None:
    """Passo 1 do assistente: os times ativos viram opção escolhível.

    O nome do time é dado do formulário; a página continua neutra (Caso A).
    """
    client, manager, _ = make_v2(tmp_path)
    with manager.unit_of_work(read_only=True) as unit_of_work:
        team = unit_of_work.identity.list_teams()[0]

    body = client.get("/login").text

    assert f'data-team-option="{team["id"]}"' in body
    assert str(team["display_name"]) in body
    assert 'data-theme="neutral"' in body
    assert "data-team=" not in body


def test_signup_refuses_athlete_that_does_not_belong_to_the_chosen_team(
    tmp_path: Path,
) -> None:
    """O time vem do formulário, então é entrada não confiável.

    Ele só restringe a lista de atletas aceitáveis, e a conferência é no
    servidor: pedir um atleta do time A dizendo ter escolhido o time B é
    recusado, e nenhuma conta nasce disso.
    """
    client, manager, _ = make_v2(tmp_path)
    with manager.unit_of_work() as unit_of_work:
        available = unit_of_work.identity.available_player_registrations()
        other_team_id = unit_of_work.identity.create_team(
            code="OUTRO_TIME",
            slug="outro-time",
            display_name="Outro Time",
            season_label="2026.2",
            actor_user_id=1,
        )
    assert available

    refused = client.post(
        "/register",
        data={
            "team_id": other_team_id,
            "team_member_id": available[0]["id"],
            "username": "invasor",
            "password": "x",
            "password_confirmation": "x",
        },
        follow_redirects=False,
    )

    assert refused.status_code == 400
    assert client.get("/api/v1/me").status_code == 401
    with manager.unit_of_work(read_only=True) as unit_of_work:
        assert unit_of_work.identity.get_user_by_username("invasor") is None


def test_player_is_denied_team_write_audit_export_and_backup(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "player", data["passwords"]["player"])
    assert client.get("/api/v1/attendance/trainings").status_code == 403
    assert client.get("/api/v1/audit").status_code == 403
    assert client.get("/api/v1/admin/audit").status_code == 403
    assert client.get("/api/v1/exports/history.csv").status_code == 403
    assert client.get("/api/v1/backup").status_code == 403
    assert client.post("/api/v1/sessions/1/finalize", headers={"X-CSRF-Token": csrf}).status_code == 403
    assert client.get("/app/presencas").status_code == 200


def test_ct_manages_structured_attack_and_defensive_positions(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    member_id = int(data["player_member_id"])

    updated = client.put(
        f"/api/v1/members/{member_id}",
        json={
            "position": "PD/PE",
            "attack_positions": ["PD", "PE"],
            "defensive_positions": ["M1", "M2"],
            "active": True,
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert updated.status_code == 200, updated.text
    member = next(item for item in updated.json()["items"] if int(item["id"]) == member_id)
    assert member["attack_positions"] == ["PD", "PE"]
    assert member["defensive_positions"] == ["M1", "M2"]
    assert member["defensive_generic"] is False
    logout(client)
    player_csrf = login(client, "player", data["passwords"]["player"])
    forbidden = client.put(
        f"/api/v1/members/{member_id}",
        json={"position": "PD", "attack_positions": ["PD"], "defensive_positions": [], "active": True},
        headers={"X-CSRF-Token": player_csrf},
    )
    assert forbidden.status_code == 403


def test_player_confirms_active_training_with_many_positions_and_justification(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    with manager.unit_of_work() as unit_of_work:
        unit_of_work.attendance.update_member(
            int(data["player_member_id"]), position="PD/PE", active=True, actor_user_id=1
        )
    ct_csrf = login(client, "ct", data["passwords"]["ct"])
    opened = open_calendar_training(client, ct_csrf, "2099-01-10")
    event_id = int(opened["calendar_event"]["id"])
    logout(client)
    player_csrf = login(client, "player", data["passwords"]["player"])
    active = client.post("/api/v1/me/attendance/active", headers={"X-CSRF-Token": player_csrf})
    assert active.status_code == 200, active.text
    item = active.json()["item"]
    assert int(item["event"]["id"]) == event_id
    saved = client.put(
        f"/api/v1/me/attendance/events/{event_id}",
        json={"response": "GOING", "positions": ["PD", "PE"], "justification": "Vou chegar alguns minutos depois.", "base_version": item["record"]["version"]},
        headers={"X-CSRF-Token": player_csrf},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["record"]["confirmation_status"] == "CONFIRMED_EARLY"
    assert body["record"]["training_positions"] == ["PD", "PE"]
    assert body["justification"] == "Vou chegar alguns minutos depois."
    fallback = client.put(
        f"/api/v1/me/attendance/events/{event_id}",
        json={"response": "GOING", "positions": [], "justification": "", "base_version": body["record"]["version"]},
        headers={"X-CSRF-Token": player_csrf},
    )
    assert fallback.status_code == 200, fallback.text
    assert fallback.json()["record"]["training_positions"] == []
    forbidden = client.put(
        f"/api/v1/me/attendance/events/{event_id}",
        json={"response": "GOING", "positions": ["GOL"], "justification": "", "base_version": fallback.json()["record"]["version"]},
        headers={"X-CSRF-Token": player_csrf},
    )
    assert forbidden.status_code == 409
    logout(client)
    login(client, "ct", data["passwords"]["ct"])
    report_payload = client.get(f"/api/v1/sessions/{int(opened['session']['id'])}")
    assert report_payload.status_code == 200, report_payload.text
    player_record = next(
        item for item in report_payload.json()["records"]
        if int(item["member_id"]) == int(data["player_member_id"])
    )
    assert player_record["effective_attack_positions"] == ["PD", "PE"]
    assert player_record["attack_position_source"] == "PROFILE_DEFAULT"
    assert report_payload.json()["coach_report"]["generated_at"]


def test_player_reconfirmation_within_three_hours_restores_effective_first_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, manager, data = make_v2(tmp_path)
    ct_csrf = login(client, "ct", data["passwords"]["ct"])
    opened = open_calendar_training(client, ct_csrf, "2099-01-10")
    event_id = int(opened["calendar_event"]["id"])
    logout(client)
    player_csrf = login(client, "player", data["passwords"]["player"])

    def save(response: str, now: str, version: int) -> dict[str, object]:
        monkeypatch.setattr(attendance_repository, "_now_iso", lambda: now)
        result = client.put(
            f"/api/v1/me/attendance/events/{event_id}",
            json={"response": response, "positions": ["PD"] if response == "GOING" else [], "justification": "", "base_version": version},
            headers={"X-CSRF-Token": player_csrf},
        )
        assert result.status_code == 200, result.text
        return result.json()["record"]

    active = client.post("/api/v1/me/attendance/active", headers={"X-CSRF-Token": player_csrf}).json()["item"]
    first = save("GOING", "2099-01-08T10:00:00-03:00", int(active["record"]["version"]))
    cancelled = save("NOT_GOING", "2099-01-09T10:00:00-03:00", int(first["version"]))
    restored = save("GOING", "2099-01-09T12:00:00-03:00", int(cancelled["version"]))

    assert restored["confirmation_status"] == "CONFIRMED_EARLY"
    assert restored["confirmation_decided_at"] == "2099-01-08T10:00:00-03:00"
    with manager.read_only_connection() as connection:
        audit = connection.execute(
            """SELECT old_confirmation_decided_at,new_confirmation_decided_at,decision_timing_note
                 FROM attendance_audit_log ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    assert tuple(audit) == (
        "2099-01-09T10:00:00-03:00",
        "2099-01-08T10:00:00-03:00",
        "Decisão anterior restaurada: reversão em até 3 horas.",
    )


def test_active_confirmation_prefers_next_training_over_stale_past_one(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    ct_csrf = login(client, "ct", data["passwords"]["ct"])
    past = open_calendar_training(client, ct_csrf, "2020-01-10")
    past_event_id = int(past["calendar_event"]["id"])
    future = open_calendar_training(client, ct_csrf, "2100-01-10")
    future_event_id = int(future["calendar_event"]["id"])
    logout(client)
    player_csrf = login(client, "player", data["passwords"]["player"])
    active = client.post("/api/v1/me/attendance/active", headers={"X-CSRF-Token": player_csrf})
    assert active.status_code == 200, active.text
    item = active.json()["item"]
    assert int(item["event"]["id"]) == future_event_id
    assert int(item["event"]["id"]) != past_event_id


def test_dev_only_has_no_sport_access_and_bob_keeps_it(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "dev", data["passwords"]["dev"])
    assert client.get("/api/v1/admin/users").status_code == 200
    assert client.get("/api/v1/attendance/trainings").status_code == 403
    logout(client)
    login(client, "bob", data["passwords"]["bob"])
    assert client.get("/api/v1/attendance/trainings").status_code == 200


def test_role_removal_and_deactivation_take_effect_immediately(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    assert client.get("/api/v1/attendance/trainings").status_code == 200
    with manager.unit_of_work() as unit_of_work:
        unit_of_work.identity.set_roles(int(data["ct_id"]), ["DEV"], actor_user_id=1)
    assert client.get("/api/v1/attendance/trainings").status_code == 403
    logout(client)
    login(client, "player", data["passwords"]["player"])
    with manager.unit_of_work() as unit_of_work:
        unit_of_work.identity.deactivate_user(int(data["player_id"]), actor_user_id=1)
    assert client.get("/api/v1/me").status_code == 401


def test_session_revocation_expiration_and_password_reset(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    with manager.unit_of_work() as unit_of_work:
        unit_of_work.identity.revoke_user_sessions(int(data["ct_id"]))
    assert client.get("/api/v1/me").status_code == 401
    login(client, "ct", data["passwords"]["ct"])
    with manager.unit_of_work() as unit_of_work:
        unit_of_work.connection.execute("UPDATE auth_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE user_id=?", (data["ct_id"],))
    assert client.get("/api/v1/me").status_code == 401
    login(client, "ct", data["passwords"]["ct"])
    with manager.unit_of_work() as unit_of_work:
        unit_of_work.identity.reset_password(int(data["ct_id"]), PasswordHasher().hash("nova-temporaria"), actor_user_id=1)
    assert client.get("/api/v1/me").status_code == 401
    login(client, "ct", "nova-temporaria")
    assert client.get("/api/v1/me").json()["must_change_password"] is False


def test_reset_password_remains_usable_and_can_be_changed_voluntarily(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    with manager.unit_of_work() as unit_of_work:
        unit_of_work.identity.reset_password(
            int(data["ct_id"]), PasswordHasher().hash("temporaria"), actor_user_id=1
        )
    csrf = login(client, "ct", "temporaria")
    assert client.get("/api/v1/attendance/trainings").status_code == 200
    changed = client.post(
        "/api/v1/me/password",
        json={"current_password": "temporaria", "new_password": "definitiva"},
        headers={"X-CSRF-Token": csrf},
    )
    assert changed.status_code == 200
    assert client.get("/api/v1/me").status_code == 401
    login(client, "ct", "definitiva")
    assert client.get("/api/v1/attendance/trainings").status_code == 200


def test_dev_admin_create_requires_csrf_and_player_link(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "bob", data["passwords"]["bob"])
    body = {
        "username": "nova-ct",
        "temporary_password": "temporaria",
        "roles": ["CT"],
        "full_name": "Nova Integrante CT",
        "team_id": data["team_id"],
    }
    assert client.post("/api/v1/admin/users", json=body).status_code == 403
    created = client.post(
        "/api/v1/admin/users", json=body, headers={"X-CSRF-Token": csrf}
    )
    assert created.status_code == 201
    listed = client.get("/api/v1/admin/users").json()["items"]
    assert next(user for user in listed if user["username"] == "nova-ct")["roles"] == ["CT"]
    invalid_player = client.post(
        "/api/v1/admin/users",
        json={
            "username": "player-sem-vinculo",
            "temporary_password": "temporaria",
            "roles": ["PLAYER"],
            "full_name": "Jogador sem vínculo",
            "team_id": data["team_id"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert invalid_player.status_code == 400
    missing_team = client.post(
        "/api/v1/admin/users",
        json={
            "username": "ct-sem-time",
            "temporary_password": "temporaria",
            "roles": ["CT"],
            "full_name": "CT sem time",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert missing_team.status_code == 400
    promoted = client.put(
        f"/api/v1/admin/users/{data['ct_id']}/roles",
        json={"roles": ["CT", "DEV"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert promoted.status_code == 200


def test_ct_write_records_actor_and_offline_creator_is_revalidated(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    payload = open_calendar_training(client, csrf, "2026-08-01")
    record = payload["records"][0]
    operation = {
        "operation_id": "actor-operation-0001",
        "member_id": record["member_id"],
        "base_version": record["version"],
        "confirmation_status": "CONFIRMED_LATE",
        "present": True,
        "notes": "Autoria",
        "creator_user_id": data["ct_id"],
    }
    accepted = client.put(
        f"/api/v1/sessions/{payload['session']['id']}/records",
        json={"operations": [operation], "offline": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert accepted.status_code == 200
    operation["operation_id"] = "actor-operation-0002"
    operation["creator_user_id"] = 1
    denied = client.put(
        f"/api/v1/sessions/{payload['session']['id']}/records",
        json={"operations": [operation], "offline": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert denied.status_code == 403
    with manager.read_only_connection() as connection:
        actor = connection.execute("SELECT actor_user_id FROM attendance_audit_log ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert actor == data["ct_id"]
    audit = client.get("/api/v1/audit")
    assert audit.status_code == 200
    assert audit.json()["items"][0]["actor_user_id"] == data["ct_id"]


def test_admin_audit_endpoint_is_scoped_to_users_manage(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "dev", data["passwords"]["dev"])
    created = client.post(
        "/api/v1/admin/users",
        json={
            "username": "nova-ct-audit",
            "temporary_password": "temporaria",
            "roles": ["CT"],
            "full_name": "Nova CT Audit",
            "team_id": data["team_id"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201, created.text
    new_user_id = created.json()["id"]

    admin_audit = client.get("/api/v1/admin/audit")
    assert admin_audit.status_code == 200, admin_audit.text
    items = admin_audit.json()["items"]
    assert any(
        item["action"] == "user.create" and item["target_id"] == str(new_user_id)
        for item in items
    )
    logout(client)

    login(client, "ct", data["passwords"]["ct"])
    assert client.get("/api/v1/admin/audit").status_code == 403
    logout(client)

    login(client, "player", data["passwords"]["player"])
    assert client.get("/api/v1/admin/audit").status_code == 403


def test_audit_log_api_exposes_old_and_new_values_for_confirmation_presence_and_notes(
    tmp_path: Path,
) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    payload = open_calendar_training(client, csrf, "2026-08-10")
    session_id = payload["session"]["id"]
    record = payload["records"][0]
    member_id = record["member_id"]

    confirm = client.put(
        f"/api/v1/sessions/{session_id}/records",
        json={
            "operations": [
                {
                    "operation_id": "audit-content-0001",
                    "member_id": member_id,
                    "base_version": record["version"],
                    "confirmation_status": "CONFIRMED_EARLY",
                    "notes": "",
                }
            ],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert confirm.status_code == 200, confirm.text
    version_after_confirm = confirm.json()["results"][0]["record"]["version"]

    mark_present = client.put(
        f"/api/v1/sessions/{session_id}/records",
        json={
            "operations": [
                {
                    "operation_id": "audit-content-0002",
                    "member_id": member_id,
                    "base_version": version_after_confirm,
                    "confirmation_status": "CONFIRMED_EARLY",
                    "present": True,
                    "notes": "",
                }
            ],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert mark_present.status_code == 200, mark_present.text
    version_after_present = mark_present.json()["results"][0]["record"]["version"]

    edit_notes = client.put(
        f"/api/v1/sessions/{session_id}/records",
        json={
            "operations": [
                {
                    "operation_id": "audit-content-0003",
                    "member_id": member_id,
                    "base_version": version_after_present,
                    "confirmation_status": "CONFIRMED_EARLY",
                    "present": True,
                    "notes": "Chegou atrasado",
                }
            ],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert edit_notes.status_code == 200, edit_notes.text

    audit = client.get("/api/v1/audit?limit=50")
    assert audit.status_code == 200
    by_operation = {item["operation_id"]: item for item in audit.json()["items"]}

    first = by_operation["audit-content-0001"]
    assert first["old_confirmation_status"] == "PENDING"
    assert first["new_confirmation_status"] == "CONFIRMED_EARLY"
    assert first["old_present"] is None
    assert first["new_present"] is None
    assert first["old_notes"] == ""
    assert first["new_notes"] == ""
    assert first["source"] == "pwa-online"
    assert first["target_id"] == f"{session_id}:{member_id}"

    second = by_operation["audit-content-0002"]
    assert second["old_confirmation_status"] == "CONFIRMED_EARLY"
    assert second["new_confirmation_status"] == "CONFIRMED_EARLY"
    assert second["old_present"] is None
    assert second["new_present"] == 1
    assert second["old_notes"] == ""
    assert second["new_notes"] == ""

    third = by_operation["audit-content-0003"]
    assert third["old_confirmation_status"] == "CONFIRMED_EARLY"
    assert third["new_confirmation_status"] == "CONFIRMED_EARLY"
    assert third["old_present"] == 1
    assert third["new_present"] == 1
    assert third["old_notes"] == ""
    assert third["new_notes"] == "Chegou atrasado"


def test_finalize_session_audit_log_records_null_present_as_zero(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    payload = open_calendar_training(client, csrf, "2026-08-11")
    session_id = payload["session"]["id"]
    untouched_member_id = payload["records"][0]["member_id"]

    finalized = client.post(
        f"/api/v1/sessions/{session_id}/finalize",
        headers={"X-CSRF-Token": csrf},
    )
    assert finalized.status_code == 200, finalized.text

    audit = client.get("/api/v1/audit?limit=200")
    assert audit.status_code == 200
    target_id = f"{session_id}:{untouched_member_id}"
    matches = [
        item
        for item in audit.json()["items"]
        if item["target_id"] == target_id and item["action"] == "attendance.finalize"
    ]
    assert len(matches) == 1
    finalize_entry = matches[0]
    assert finalize_entry["old_confirmation_status"] == "PENDING"
    assert finalize_entry["new_confirmation_status"] == "PENDING"
    assert finalize_entry["old_present"] is None
    assert finalize_entry["new_present"] == 0


def test_audit_endpoint_respects_limit_query_param(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    payload = open_calendar_training(client, csrf, "2026-08-12")
    session_id = payload["session"]["id"]
    records = payload["records"][:3]
    operations = [
        {
            "operation_id": f"audit-limit-{index:04d}",
            "member_id": record["member_id"],
            "base_version": record["version"],
            "confirmation_status": "CONFIRMED_EARLY",
            "notes": "",
        }
        for index, record in enumerate(records)
    ]
    written = client.put(
        f"/api/v1/sessions/{session_id}/records",
        json={"operations": operations},
        headers={"X-CSRF-Token": csrf},
    )
    assert written.status_code == 200, written.text

    limited = client.get("/api/v1/audit?limit=2")
    assert limited.status_code == 200
    assert len(limited.json()["items"]) == 2

    floor = client.get("/api/v1/audit?limit=0")
    assert floor.status_code == 200
    assert len(floor.json()["items"]) == 1

    negative = client.get("/api/v1/audit?limit=-5")
    assert negative.status_code == 200
    assert len(negative.json()["items"]) == 1

    default = client.get("/api/v1/audit")
    assert default.status_code == 200
    assert len(default.json()["items"]) == len(records)


def test_player_report_is_scoped_in_query_and_excludes_internal_notes(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    payload = open_calendar_training(client, csrf, "2026-08-02")
    records = payload["records"]
    operations = []
    for index, record in enumerate(records[:2]):
        operations.append(
            {
                "operation_id": f"scope-operation-{index:04d}",
                "member_id": record["member_id"],
                "base_version": record["version"],
                "confirmation_status": "CONFIRMED_LATE",
                "present": True,
                "notes": f"nota interna {index}",
            }
        )
    written = client.put(
        f"/api/v1/sessions/{payload['session']['id']}/records",
        json={"operations": operations, "offline": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert written.status_code == 200
    logout(client)
    login(client, "player", data["passwords"]["player"])
    own = client.get("/api/v1/me/attendance")
    assert own.status_code == 200
    assert len(own.json()["items"]) == 1
    assert "notes" not in own.json()["items"][0]
    page = client.get("/app/meu-relatorio")
    assert page.status_code == 200
    assert "nota interna" not in page.text


def test_offline_assets_are_namespaced_and_logout_locks_without_cross_user_unlock(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    app_js = client.get("/static/app.js").text
    platform_js = client.get("/static/platform.js").text
    assert "handball-offline-v2" in app_js
    assert "vault:${state.userId}:${state.teamId}:2" in app_js
    assert "creator_user_id: state.userId" in app_js
    assert "O cofre pertence a outro usuário ou time" in app_js
    assert 'new Event("handball:lock-offline")' in platform_js
    assert "objectStore(\"secure\").clear()" not in platform_js


def test_dev_creates_team_and_ct_account_scoped_to_it(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "bob", data["passwords"]["bob"])
    created_team = client.post(
        "/api/v1/admin/teams",
        json={"code": "HM_IME_SUB17", "slug": "hm-ime-sub17", "display_name": "HM-IME Sub-17"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created_team.status_code == 201, created_team.text
    team_id = created_team.json()["id"]
    assert team_id != data["team_id"]

    created_ct = client.post(
        "/api/v1/admin/users",
        json={
            "username": "ct-sub17",
            "temporary_password": "temporaria",
            "roles": ["CT"],
            "full_name": "CT Sub-17",
            "team_id": team_id,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created_ct.status_code == 201, created_ct.text
    with manager.read_only_connection() as connection:
        membership = connection.execute(
            "SELECT team_id FROM team_memberships WHERE person_id="
            "(SELECT person_id FROM users WHERE username='ct-sub17')"
        ).fetchone()
    assert int(membership["team_id"]) == team_id

    # o time novo ainda não tem elenco vinculado (limitação documentada em
    # docs/HM-IME-USUARIOS-E-AUTORIZACAO.md §11 e no backlog)
    available = client.get(f"/api/v1/admin/teams/{team_id}/available-players", headers={"X-CSRF-Token": csrf})
    assert available.status_code == 200
    assert available.json()["items"] == []

    # o time HM-IME original continua funcionando sem o lookup fixo antigo
    created_hm_ime_ct = client.post(
        "/api/v1/admin/users",
        json={
            "username": "outro-ct-hm-ime",
            "temporary_password": "temporaria",
            "roles": ["CT"],
            "full_name": "Outro CT HM-IME",
            "team_id": data["team_id"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created_hm_ime_ct.status_code == 201, created_hm_ime_ct.text


def test_dev_create_player_rejects_team_mismatch(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "bob", data["passwords"]["bob"])
    other_team = client.post(
        "/api/v1/admin/teams",
        json={"code": "OUTRO", "slug": "outro", "display_name": "Outro Time"},
        headers={"X-CSRF-Token": csrf},
    ).json()
    with manager.unit_of_work(read_only=True) as unit_of_work:
        available = unit_of_work.identity.available_player_registrations()
    assert available
    mismatched = client.post(
        "/api/v1/admin/users",
        json={
            "username": "jogador-time-errado",
            "temporary_password": "temporaria",
            "roles": ["PLAYER"],
            "linked_player_id": available[0]["id"],
            "team_id": other_team["id"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert mismatched.status_code == 400


def test_ct_creates_player_account_within_own_team(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    available = client.get(f"/api/v1/team/available-players?team_id={data['team_id']}")
    assert available.status_code == 200
    items = available.json()["items"]
    assert items
    chosen = items[0]
    created = client.post(
        "/api/v1/team/player-accounts",
        json={
            "team_id": data["team_id"],
            "team_member_id": chosen["id"],
            "username": "jogador-via-ct",
            "temporary_password": "temporaria",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    with manager.read_only_connection() as connection:
        roles = {row[0] for row in connection.execute("SELECT role_code FROM system_roles WHERE user_id=?", (user_id,))}
    assert roles == {"PLAYER"}
    logout(client)
    login(client, "jogador-via-ct", "temporaria")
    assert client.get("/api/v1/me").json()["linked_player_id"] == chosen["id"]


def test_ct_cannot_create_player_account_outside_own_team(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    dev_csrf = login(client, "bob", data["passwords"]["bob"])
    other_team = client.post(
        "/api/v1/admin/teams",
        json={"code": "OUTRO2", "slug": "outro-2", "display_name": "Outro Time 2"},
        headers={"X-CSRF-Token": dev_csrf},
    ).json()
    logout(client)
    ct_csrf = login(client, "ct", data["passwords"]["ct"])
    assert client.get(f"/api/v1/team/available-players?team_id={other_team['id']}").status_code == 403
    denied_create = client.post(
        "/api/v1/team/player-accounts",
        json={"team_id": other_team["id"], "team_member_id": 1, "username": "x", "temporary_password": "temporaria"},
        headers={"X-CSRF-Token": ct_csrf},
    )
    assert denied_create.status_code == 403


def test_player_cannot_access_team_player_account_endpoints(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "player", data["passwords"]["player"])
    assert client.get(f"/api/v1/team/available-players?team_id={data['team_id']}").status_code == 403
    denied = client.post(
        "/api/v1/team/player-accounts",
        json={"team_id": data["team_id"], "team_member_id": 1, "username": "x", "temporary_password": "temporaria"},
        headers={"X-CSRF-Token": csrf},
    )
    assert denied.status_code == 403


def test_teams_admin_endpoints_are_dev_only(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    assert client.get("/api/v1/admin/teams").status_code == 403
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    assert client.post(
        "/api/v1/admin/teams",
        json={"code": "X", "slug": "x", "display_name": "X"},
        headers={"X-CSRF-Token": csrf},
    ).status_code == 403


def test_set_roles_requires_existing_team_membership_for_ct(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    with manager.unit_of_work() as unit_of_work:
        with pytest.raises(ValueError, match="vínculo"):
            unit_of_work.identity.set_roles(int(data["dev_id"]), ["CT"], actor_user_id=1)


def test_admin_usuarios_page_renders_teams_panel_and_team_select(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "bob", data["passwords"]["bob"])
    page = client.get("/app/admin/usuarios")
    assert page.status_code == 200
    body = page.text
    assert "Times" in body
    assert "Criar time" in body
    assert 'id="new-team-code"' in body
    assert 'id="new-user-team"' in body
    assert 'id="new-linked-player"' in body
    assert "HM-IME" in body


def test_ct_roster_page_renders_player_account_panel(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    # O cadastro do elenco (e a criação de conta de jogador) migrou da chamada
    # para o módulo Gestão de Elenco; a chamada mantém só o atalho.
    page = client.get("/app/elenco")
    assert page.status_code == 200
    body = page.text
    assert 'id="player-account-form"' in body
    assert "Criar conta de jogador" in body
    assert 'id="player-account-member"' in body
    attendance_page = client.get("/app/presencas")
    assert attendance_page.status_code == 200
    assert 'href="/app/elenco"' in attendance_page.text


def test_player_roster_page_has_no_player_account_panel(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "player", data["passwords"]["player"])
    page = client.get("/app/presencas")
    assert page.status_code == 200
    assert 'id="player-account-form"' not in page.text
