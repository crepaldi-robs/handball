from __future__ import annotations

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from attendance.config import AppSettings
from attendance.web import create_app


def make_client(tmp_path) -> TestClient:
    settings = AppSettings(
        db_path=tmp_path / "web.db",
        admin_username="roberto",
        password_hash=PasswordHasher().hash("senha-de-teste-forte"),
        secret_key="s" * 64,
        cookie_secure=False,
        backup_dir=tmp_path / "backups",
    )
    return TestClient(create_app(settings))


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
    assert client.get("/api/v1/history").status_code == 401
    assert client.post(
        "/login",
        data={"username": "roberto", "password": "errada"},
    ).status_code == 401

    login(client)
    response = client.get("/app")
    assert response.status_code == 200
    assert "Registro de Presenças" in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert "noindex" in response.text


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
    assert client.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"
    backup = client.get("/api/v1/backup", headers={"X-CSRF-Token": csrf})
    assert backup.status_code == 200
    assert backup.content.startswith(b"SQLite format 3")
