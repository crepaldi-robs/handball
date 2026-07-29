from __future__ import annotations

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
import pytest

from starlette.requests import Request

from handball.application import create_app
from handball.core.auth import LoginLimiter, login_client_key
from handball.core.config import AppSettings
from handball.database import (
    LATEST_SCHEMA_VERSION,
    AttendanceRepository,
    DatabaseCompatibilityError,
    DatabaseManager,
)
from handball.database.migrations import DatabaseMigrator, logical_fingerprint


def make_client(tmp_path, *, trusted_proxies: frozenset[str] | None = None) -> TestClient:
    database_path = tmp_path / "web.db"
    database_manager = DatabaseManager(
        database_path,
        backup_dir=tmp_path / "backups",
    )
    database_manager.bootstrap()
    password_hash = PasswordHasher().hash("senha-de-teste-forte")
    DatabaseMigrator(database_path).apply_pending(
        expected_fingerprint=logical_fingerprint(database_path),
        legacy_admin=("roberto", password_hash),
        app_version="pytest",
        origin="pytest",
    )
    settings = AppSettings(
        admin_username="roberto",
        password_hash=password_hash,
        secret_key="s" * 64,
        config_path=tmp_path / "app-config.json",
        cookie_secure=False,
        release_id="test-release",
        **({"trusted_proxies": trusted_proxies} if trusted_proxies else {}),
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
        "schema_version": LATEST_SCHEMA_VERSION,
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


def test_config_admin_is_not_a_credential_anymore(tmp_path):
    """A ponte de release morreu: app-config.json nao autentica ninguem.

    Antes, se o banco ainda fosse v1, o par admin_username/password_hash da
    configuracao logava com papeis DEV+CT fixos. Com o esquema em v4 esse
    caminho era codigo morto perigoso; aqui garantimos que ele nao volta.
    """

    database_path = tmp_path / "sem-legado.db"
    manager = DatabaseManager(database_path, backup_dir=tmp_path / "backups")
    manager.bootstrap()
    password_hash = PasswordHasher().hash("senha-de-teste-forte")
    DatabaseMigrator(database_path).apply_pending(
        expected_fingerprint=logical_fingerprint(database_path),
        legacy_admin=("roberto", password_hash),
        app_version="pytest",
        origin="pytest",
    )

    # A configuracao aponta para alguem que nao tem conta na tabela users.
    settings = AppSettings(
        admin_username="fantasma",
        password_hash=password_hash,
        secret_key="s" * 64,
        config_path=tmp_path / "app-config.json",
        cookie_secure=False,
        release_id="test-release",
    )
    client = TestClient(create_app(settings, database_manager=manager))

    response = client.post(
        "/login",
        data={"username": "fantasma", "password": "senha-de-teste-forte"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert "set-cookie" not in response.headers

    # E um cookie assinado com a secret_key tambem nao vale mais nada.
    client.cookies.set("handball_session", "qualquer-coisa-assinada")
    assert client.get("/api/v1/auth/session").status_code == 401


def _request_from(client_host: str | None, **headers: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/login",
            "headers": [
                (name.replace("_", "-").encode(), value.encode())
                for name, value in headers.items()
            ],
            "client": (client_host, 51234) if client_host else None,
        }
    )


def test_login_client_key_uses_original_ip_only_behind_trusted_proxy():
    trusted = frozenset({"127.0.0.1"})

    # Atrás do túnel: o peer é o loopback e o cabeçalho do Cloudflare vale.
    assert (
        login_client_key(
            _request_from("127.0.0.1", cf_connecting_ip="203.0.113.7"), trusted
        )
        == "203.0.113.7"
    )

    # X-Forwarded-For é o segundo recurso, e só a primeira entrada conta.
    assert (
        login_client_key(
            _request_from("127.0.0.1", x_forwarded_for="203.0.113.9, 10.0.0.1"),
            trusted,
        )
        == "203.0.113.9"
    )

    # Peer desconhecido não pode forjar identidade: vale o endereço observado.
    assert (
        login_client_key(
            _request_from("198.51.100.4", cf_connecting_ip="203.0.113.7"), trusted
        )
        == "198.51.100.4"
    )

    # Sem cabeçalho algum, o peer confiável responde por si mesmo.
    assert login_client_key(_request_from("127.0.0.1"), trusted) == "127.0.0.1"
    assert login_client_key(_request_from(None), trusted) == "unknown"


def test_login_limit_is_per_client_behind_the_tunnel(tmp_path, monkeypatch):
    """Um atacante não pode bloquear o login de todo mundo pelo túnel."""

    clock = {"now": 3_000.0}
    limiter = LoginLimiter(monotonic=lambda: clock["now"])
    monkeypatch.setattr("handball.core.auth.LoginLimiter", lambda: limiter)
    client = make_client(tmp_path, trusted_proxies=frozenset({"testclient"}))

    attacker = {"CF-Connecting-IP": "203.0.113.66"}
    for _ in range(5):
        client.post(
            "/login",
            data={"username": "roberto", "password": "errada"},
            headers=attacker,
        )

    blocked = client.post(
        "/login",
        data={"username": "roberto", "password": "errada"},
        headers=attacker,
    )
    assert blocked.status_code == 429

    # Outro cliente, vindo pelo mesmo túnel, continua conseguindo entrar.
    innocent = client.post(
        "/login",
        data={"username": "roberto", "password": "senha-de-teste-forte"},
        headers={"CF-Connecting-IP": "203.0.113.99"},
        follow_redirects=False,
    )
    assert innocent.status_code == 303
    assert "handball_session=" in innocent.headers["set-cookie"]


def test_legacy_session_endpoint_does_not_create_arbitrary_training(tmp_path):
    client = make_client(tmp_path)
    login(client)
    response = client.get("/api/v1/session?training_date=2026-07-25")
    assert response.status_code == 410
    assert "calendário" in response.json()["detail"]


def test_pwa_assets_and_backup(tmp_path):
    client = make_client(tmp_path)
    csrf = login(client)
    assert client.get("/static/manifest.webmanifest").status_code == 200
    worker = client.get("/sw.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/"
    assert 'handball-shell-v8' in worker.text
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
