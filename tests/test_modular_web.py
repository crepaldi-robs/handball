from __future__ import annotations

import json

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from handball.application import create_app
from handball.core.config import AppSettings
from handball.database import DatabaseManager
from handball.database.migrations import DatabaseMigrator, logical_fingerprint


def make_client(tmp_path, *, secure_cookie: bool = False) -> tuple[TestClient, DatabaseManager]:
    database_manager = DatabaseManager(
        tmp_path / "modular-web.db",
        backup_dir=tmp_path / "backups",
    )
    database_manager.bootstrap()
    password_hash = PasswordHasher().hash("senha-de-teste-forte")
    DatabaseMigrator(tmp_path / "modular-web.db").apply_pending(
        expected_fingerprint=logical_fingerprint(tmp_path / "modular-web.db"),
        legacy_admin=("roberto", password_hash),
        app_version="pytest",
        origin="pytest",
    )
    settings = AppSettings(
        admin_username="roberto",
        password_hash=password_hash,
        secret_key="s" * 64,
        config_path=tmp_path / "app-config.json",
        cookie_secure=secure_cookie,
        release_id="modular-test",
    )
    return (
        TestClient(
            create_app(settings, database_manager=database_manager),
            base_url="https://testserver" if secure_cookie else "http://testserver",
        ),
        database_manager,
    )


def login(client: TestClient):
    response = client.post(
        "/login",
        data={"username": "roberto", "password": "senha-de-teste-forte"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    return response


@pytest.mark.parametrize(
    "path",
    (
        "/app",
        "/app/presencas",
        "/app/estatisticas",
        "/app/calendario",
        "/app/playbook",
        "/app/consultas",
    ),
)
def test_every_application_page_redirects_anonymous_users(tmp_path, path):
    client, _ = make_client(tmp_path)

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_hub_exposes_all_modules_as_keyboard_accessible_links(tmp_path):
    client, _ = make_client(tmp_path)
    login(client)

    response = client.get("/app")

    assert response.status_code == 200
    # Fase 2 do redesenho: quem tem chamada de time (CT/DEV+CT, como o admin
    # de bootstrap) cai na fila "Precisa de você", não no hero de boas-vindas.
    # A grade de módulos continua alcançável em "Todos os módulos" — daí os
    # hrefs abaixo ainda aparecerem sem mudança.
    assert '<h2 id="ct-queue-title"' in response.text
    assert 'href="/app/presencas"' in response.text
    assert 'href="/app/estatisticas"' in response.text
    assert 'href="/app/calendario"' in response.text
    assert 'href="/app/playbook"' in response.text
    assert 'href="/app/consultas"' in response.text
    assert "Disponível" in response.text
    assert response.text.count("Em preparação") == 1
    assert 'form method="post" action="/logout" data-platform-logout' in response.text


@pytest.mark.parametrize(
    ("path", "title"),
    (
        ("/app/estatisticas", "Estatísticas"),
    ),
)
def test_authenticated_skeletons_are_read_only_and_share_navigation(
    tmp_path,
    path,
    title,
):
    client, database_manager = make_client(tmp_path)
    login(client)
    fingerprint_before = database_manager.logical_fingerprint()

    response = client.get(path)

    assert response.status_code == 200
    assert f'<h1 id="module-title">{title}</h1>' in response.text
    assert "Em preparação" in response.text
    assert 'href="/app"' in response.text
    assert 'action="/logout" data-platform-logout' in response.text
    assert "/static/platform.js" in response.text
    assert database_manager.logical_fingerprint() == fingerprint_before


@pytest.mark.parametrize(
    "page",
    (
        "/app",
        "/app/presencas",
        "/app/estatisticas",
        "/app/calendario",
        "/app/playbook",
        "/app/consultas",
    ),
)
def test_one_logout_invalidates_the_shared_session_from_every_module(tmp_path, page):
    client, _ = make_client(tmp_path)
    login(client)
    assert client.get(page).status_code == 200

    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    response = client.post(
        "/logout", data={"csrf_token": csrf}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert "handball_session=" in response.headers["set-cookie"]
    protected = client.get(page, follow_redirects=False)
    assert protected.status_code == 303
    assert protected.headers["location"] == "/login"


def test_shared_cookie_retains_security_contract(tmp_path):
    client, _ = make_client(tmp_path, secure_cookie=True)

    response = login(client)

    cookie = response.headers["set-cookie"]
    assert "handball_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie


def test_pwa_v9_keeps_last_calendar_navigation_read_only_offline(tmp_path):
    client, _ = make_client(tmp_path)
    login(client)

    manifest = json.loads(client.get("/static/manifest.webmanifest").text)
    worker = client.get("/sw.js").text
    platform = client.get("/static/platform.js").text

    assert manifest["start_url"] == "/app"
    assert 'const CACHE_NAME = "handball-shell-v14"' in worker
    # A identidade visual só sobrevive offline se os tokens e as fontes
    # auto-hospedadas estiverem no shell — sem isso a chamada no ginásio sem
    # sinal cai no CSS do navegador.
    assert '"/static/css/tokens.generated.css"' in worker
    assert '"/static/css/hm-ime-expressive.css"' in worker
    assert '"/static/fonts/inter-latin.woff2"' in worker
    assert '"/static/fonts/barlow-condensed-700-latin.woff2"' in worker
    assert '["/app", "/app"]' in worker
    assert '["/app/presencas", "/app/presencas"]' in worker
    assert '["/app/calendario", "/app/calendario"]' in worker
    assert '["/app/playbook", "/app/playbook"]' in worker
    assert '"/static/calendar.js"' in worker
    assert '"/static/playbook.js"' in worker
    assert '"/static/hm-ime-logo.jpg"' in worker
    assert 'pathname === "/app/estatisticas"' in worker
    assert 'pathname === "/app/calendario"' not in worker
    assert 'pathname === "/app/consultas"' in worker
    assert 'pathname.startsWith("/roberto/")' in worker
    assert 'pathname.startsWith("/api/")' in worker
    assert "data-platform-logout" in client.get("/app").text
    assert "lockOfflineRuntime" in platform
    assert "handball:lock-offline" in platform
    assert 'key.startsWith("handball-calendar-")' in platform
    assert 'key.startsWith("handball-shell-")' in platform
