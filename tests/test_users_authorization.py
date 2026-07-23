from __future__ import annotations

import sqlite3
from pathlib import Path

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from handball.application import create_app
from handball.core.authorization import Permission, ROLE_PERMISSIONS
from handball.core.config import AppSettings
from handball.database import DatabaseManager
from handball.database.migrations import DatabaseMigrator, logical_fingerprint, verify_database


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
        player = unit_of_work.identity.list_people_and_players()["players"][0]
        player_id = unit_of_work.identity.create_user(
            person_id=int(player["id"]),
            username="player",
            password_hash=PasswordHasher().hash(passwords["player"]),
            roles=["PLAYER"],
            linked_player_id=int(player["team_member_id"]),
            actor_user_id=1,
        )
        ct_person = unit_of_work.identity.create_person("Comissão Teste", "CT Teste")
        ct_id = unit_of_work.identity.create_user(
            person_id=ct_person,
            username="ct",
            password_hash=PasswordHasher().hash(passwords["ct"]),
            roles=["CT"],
            linked_player_id=None,
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
    client = TestClient(create_app(settings, database_manager=manager))
    return client, manager, {
        "passwords": passwords,
        "player_id": player_id,
        "player_member_id": int(player["team_member_id"]),
        "ct_id": ct_id,
        "dev_id": dev_id,
        "before_ids": [int(item["id"]) for item in before_ids],
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


def test_permission_matrix_is_typed_and_dev_does_not_imply_sport() -> None:
    assert Permission.USERS_MANAGE in ROLE_PERMISSIONS["DEV"]
    assert Permission.ATTENDANCE_READ_TEAM not in ROLE_PERMISSIONS["DEV"]
    assert Permission.ATTENDANCE_WRITE in ROLE_PERMISSIONS["CT"]
    assert ROLE_PERMISSIONS["PLAYER"] == frozenset(
        {Permission.ATTENDANCE_READ_SELF, Permission.REPORTS_READ_SELF}
    )


def test_v2_migration_preserves_members_and_materializes_bob(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    assert verify_database(manager.db_path)["ok"] is True
    assert DatabaseMigrator(manager.db_path).status().current_version == 2
    assert [int(item["id"]) for item in manager.attendance_repository().list_members()] == data["before_ids"]
    with manager.read_only_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM player_user_links").fetchone()[0] == len(data["before_ids"])
        bob = connection.execute("SELECT username,password_hash FROM users WHERE username='bob'").fetchone()
        roles = {row[0] for row in connection.execute("SELECT role_code FROM system_roles WHERE user_id=1")}
    assert bob is not None and PasswordHasher().verify(bob["password_hash"], "senha-bob")
    assert roles == {"DEV", "CT"}
    assert client.get("/ready").json()["schema_version"] == 2


def test_logins_and_scoped_hub(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "bob", data["passwords"]["bob"])
    assert client.get("/api/v1/admin/users").status_code == 200
    assert client.get("/api/v1/session", params={"training_date": "2026-08-01"}).status_code == 200
    logout(client)
    login(client, "ct", data["passwords"]["ct"])
    assert client.get("/api/v1/session", params={"training_date": "2026-08-01"}).status_code == 200
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


def test_player_is_denied_team_write_audit_export_and_backup(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "player", data["passwords"]["player"])
    assert client.get("/api/v1/session", params={"training_date": "2026-08-01"}).status_code == 403
    assert client.get("/api/v1/audit").status_code == 403
    assert client.get("/api/v1/exports/history.csv").status_code == 403
    assert client.get("/api/v1/backup").status_code == 403
    assert client.post("/api/v1/sessions/1/finalize", headers={"X-CSRF-Token": csrf}).status_code == 403
    assert client.get("/app/presencas").status_code == 403


def test_dev_only_has_no_sport_access_and_bob_keeps_it(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    login(client, "dev", data["passwords"]["dev"])
    assert client.get("/api/v1/admin/users").status_code == 200
    assert client.get("/api/v1/session", params={"training_date": "2026-08-01"}).status_code == 403
    logout(client)
    login(client, "bob", data["passwords"]["bob"])
    assert client.get("/api/v1/session", params={"training_date": "2026-08-01"}).status_code == 200


def test_role_removal_and_deactivation_take_effect_immediately(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    login(client, "ct", data["passwords"]["ct"])
    assert client.get("/api/v1/session", params={"training_date": "2026-08-01"}).status_code == 200
    with manager.unit_of_work() as unit_of_work:
        unit_of_work.identity.set_roles(int(data["ct_id"]), ["DEV"], actor_user_id=1)
    assert client.get("/api/v1/session", params={"training_date": "2026-08-01"}).status_code == 403
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
    assert client.get("/api/v1/me").json()["must_change_password"] is True


def test_temporary_password_blocks_permissions_until_own_change(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    with manager.unit_of_work() as unit_of_work:
        unit_of_work.identity.reset_password(
            int(data["ct_id"]), PasswordHasher().hash("temporaria"), actor_user_id=1
        )
    csrf = login(client, "ct", "temporaria")
    assert client.get("/api/v1/session", params={"training_date": "2026-08-01"}).status_code == 403
    changed = client.post(
        "/api/v1/me/password",
        json={"current_password": "temporaria", "new_password": "definitiva"},
        headers={"X-CSRF-Token": csrf},
    )
    assert changed.status_code == 200
    assert client.get("/api/v1/me").status_code == 401
    login(client, "ct", "definitiva")
    assert client.get("/api/v1/session", params={"training_date": "2026-08-01"}).status_code == 200


def test_dev_admin_create_requires_csrf_and_player_link(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "bob", data["passwords"]["bob"])
    body = {
        "username": "nova-ct",
        "temporary_password": "temporaria",
        "roles": ["CT"],
        "full_name": "Nova Integrante CT",
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
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert invalid_player.status_code == 400
    promoted = client.put(
        f"/api/v1/admin/users/{data['dev_id']}/roles",
        json={"roles": ["DEV", "CT"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert promoted.status_code == 200


def test_ct_write_records_actor_and_offline_creator_is_revalidated(tmp_path: Path) -> None:
    client, manager, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    payload = client.get("/api/v1/session", params={"training_date": "2026-08-01"}).json()
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


def test_player_report_is_scoped_in_query_and_excludes_internal_notes(tmp_path: Path) -> None:
    client, _, data = make_v2(tmp_path)
    csrf = login(client, "ct", data["passwords"]["ct"])
    payload = client.get("/api/v1/session", params={"training_date": "2026-08-02"}).json()
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
