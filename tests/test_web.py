from __future__ import annotations

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
import pytest

from handball.application import create_app
from handball.core.auth import LoginLimiter
from handball.core.config import AppSettings
from handball.database import (
    AttendanceRepository,
    DatabaseCompatibilityError,
    DatabaseManager,
)


def make_client(tmp_path) -> TestClient:
    database_path = tmp_path / "web.db"
    database_manager = DatabaseManager(
        database_path,
        backup_dir=tmp_path / "backups",
    )
    database_manager.bootstrap()
    settings = AppSettings(
        admin_username="roberto",
        password_hash=PasswordHasher().hash("senha-de-teste-forte"),
        secret_key="s" * 64,
        config_path=tmp_path / "app-config.json",
        cookie_secure=False,
        release_id="test-release",
    )
    return TestClient(create_app(settings, database_manager=database_manager))


def login(client: TestClient) -> str:
    response = client.post(
        "/login",
        data={"username": "roberto", "password": "senha-de-teste-forte"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session = client.get("/api/v1/auth/session")
    assert session.status_code == 200
    return session.json()["csrf_token"]


def test_authentication_and_security_headers(tmp_path):
    client = make_client(tmp_path)
    readiness = client.get("/ready")
    assert readiness.status_code == 200
    assert readiness.json() == {
        "status": "ok",
        "database": "ready",
        "schema_version": 1,
        "release_id": "test-release",
    }
    assert client.get("/api/v1/history").status_code == 401
    assert client.post(
        "/login",
        data={"username": "roberto", "password": "errada"},
    ).status_code == 401

    login(client)
    hub = client.get("/app")
    assert hub.status_code == 200
    assert "Hub Handebol" in hub.text
    response = client.get("/app/presencas")
    assert response.status_code == 200
    assert "Registro de Presenças" in response.text
    assert 'id="metric-details"' in response.text
    assert 'id="metric-details-list"' in response.text
    assert 'aria-live="polite"' in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert "noindex" in response.text


def test_readiness_reports_the_schema_version_read_from_database(
    tmp_path,
    monkeypatch,
):
    client = make_client(tmp_path)
    monkeypatch.setattr(
        DatabaseManager,
        "validate_existing",
        lambda _repository, **_kwargs: 7,
    )

    readiness = client.get("/ready")

    assert readiness.status_code == 200
    assert readiness.json()["schema_version"] == 7


def test_login_blocks_on_limit_and_releases_after_policy_window(
    tmp_path,
    monkeypatch,
):
    clock = {"now": 1_000.0}
    limiter = LoginLimiter(monotonic=lambda: clock["now"])
    monkeypatch.setattr("handball.core.auth.LoginLimiter", lambda: limiter)
    client = make_client(tmp_path)

    for _ in range(4):
        response = client.post(
            "/login",
            data={"username": "roberto", "password": "errada"},
        )
        assert response.status_code == 401
        assert "Usuário ou senha inválidos." in response.text

    blocked = client.post(
        "/login",
        data={"username": "roberto", "password": "errada"},
    )
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "900"
    assert "set-cookie" not in blocked.headers
    assert "Limite de 5 tentativas atingido." in blocked.text
    assert "por até 15 minutos." in blocked.text
    assert "Tente novamente em 15 minutos." in blocked.text
    assert 'role="alert"' in blocked.text

    clock["now"] += 60
    correct_but_blocked = client.post(
        "/login",
        data={"username": "roberto", "password": "senha-de-teste-forte"},
        follow_redirects=False,
    )
    assert correct_but_blocked.status_code == 429
    assert correct_but_blocked.headers["retry-after"] == "840"
    assert "set-cookie" not in correct_but_blocked.headers
    assert "Tente novamente em 14 minutos." in correct_but_blocked.text

    clock["now"] += 840
    released = client.post(
        "/login",
        data={"username": "roberto", "password": "senha-de-teste-forte"},
        follow_redirects=False,
    )
    assert released.status_code == 303
    assert released.headers["location"] == "/app"
    assert "handball_session=" in released.headers["set-cookie"]


def test_login_alert_uses_changed_policy_values(tmp_path, monkeypatch):
    clock = {"now": 2_000.0}
    limiter = LoginLimiter(
        limit=3,
        window_seconds=90,
        monotonic=lambda: clock["now"],
    )
    monkeypatch.setattr("handball.core.auth.LoginLimiter", lambda: limiter)
    client = make_client(tmp_path)

    for _ in range(2):
        response = client.post(
            "/login",
            data={"username": "roberto", "password": "errada"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/login",
        data={"username": "roberto", "password": "errada"},
    )
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "90"
    assert "Limite de 3 tentativas atingido." in blocked.text
    assert "por até 1 minuto e 30 segundos." in blocked.text
    assert "Tente novamente em 1 minuto e 30 segundos." in blocked.text


def test_session_sync_requires_csrf_and_returns_conflict(tmp_path):
    client = make_client(tmp_path)
    csrf = login(client)
    payload = client.get("/api/v1/session?training_date=2026-07-25").json()
    record = payload["records"][0]
    endpoint = f"/api/v1/sessions/{payload['session']['id']}/records"
    body = {
        "operations": [
            {
                "operation_id": "web-operation-0001",
                "member_id": record["member_id"],
                "base_version": record["version"],
                "confirmation_status": "CONFIRMED_LATE",
                "present": True,
                "notes": "Pelo navegador",
            }
        ],
        "offline": False,
    }

    assert client.put(endpoint, json=body).status_code == 403
    accepted = client.put(endpoint, json=body, headers={"X-CSRF-Token": csrf})
    assert accepted.status_code == 200
    assert accepted.json()["results"][0]["status"] == "accepted"

    body["operations"][0]["operation_id"] = "web-operation-0002"
    body["operations"][0]["notes"] = "Versão antiga"
    conflict = client.put(endpoint, json=body, headers={"X-CSRF-Token": csrf})
    assert conflict.json()["results"][0]["status"] == "conflict"


def test_pwa_assets_and_backup(tmp_path):
    client = make_client(tmp_path)
    csrf = login(client)
    assert client.get("/static/manifest.webmanifest").status_code == 200
    worker = client.get("/sw.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/"
    assert 'handball-shell-v4' in worker.text
    assert '"/app/presencas"' in worker.text
    app_script = client.get("/static/app.js")
    assert app_script.status_code == 200
    assert 'card.setAttribute("aria-controls", "metric-details")' in app_script.text
    assert 'item.textContent = record.name' in app_script.text
    assert client.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"
    backup = client.get("/api/v1/backup", headers={"X-CSRF-Token": csrf})
    assert backup.status_code == 200
    assert backup.content.startswith(b"SQLite format 3")


def test_web_startup_refuses_to_recreate_missing_database(tmp_path):
    database_path = tmp_path / "missing.db"
    settings = AppSettings(
        admin_username="roberto",
        password_hash=PasswordHasher().hash("senha-de-teste-forte"),
        secret_key="s" * 64,
        config_path=tmp_path / "app-config.json",
        cookie_secure=False,
    )
    database_manager = DatabaseManager(
        database_path,
        backup_dir=tmp_path / "backups",
    )

    with pytest.raises(DatabaseCompatibilityError, match="não encontrado"):
        create_app(settings, database_manager=database_manager)

    assert not database_path.exists()


def test_maintenance_mode_blocks_all_business_routes_without_touching_database(
    tmp_path,
):
    database_path = tmp_path / "maintenance.db"
    repository = AttendanceRepository(database_path)
    repository.bootstrap()
    fingerprint_before = repository.logical_fingerprint()
    maintenance_file = tmp_path / "maintenance-mode"
    maintenance_file.write_text("APP_ONLY\n", encoding="utf-8")
    settings = AppSettings(
        admin_username="roberto",
        password_hash=PasswordHasher().hash("senha-de-teste-forte"),
        secret_key="s" * 64,
        config_path=tmp_path / "app-config.json",
        cookie_secure=False,
        release_id="maintenance-release",
        maintenance_file=maintenance_file,
    )
    database_manager = DatabaseManager(
        database_path,
        backup_dir=tmp_path / "backups",
    )
    client = TestClient(create_app(settings, database_manager=database_manager))

    assert client.get("/health").status_code == 200
    readiness = client.get("/ready")
    assert readiness.status_code == 200
    assert readiness.json()["release_id"] == "maintenance-release"
    for method, path in (
        ("get", "/login"),
        ("get", "/app"),
        ("get", "/api/v1/history"),
        ("post", "/login"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 503
        assert response.json()["status"] == "maintenance"
        assert response.headers["retry-after"] == "30"

    assert repository.logical_fingerprint() == fingerprint_before
