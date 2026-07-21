from __future__ import annotations

import json
from argparse import Namespace

from argon2 import PasswordHasher

from attendance.cli import initialize, reset_password


def test_initialize_accepts_one_character_password(tmp_path, monkeypatch):
    config_path = tmp_path / "app-config.json"
    answers = iter(["x", "x"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "roberto")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    result = initialize(
        Namespace(
            config_path=config_path,
            db_path=tmp_path / "presencas.db",
            backup_dir=tmp_path / "backups",
            secure_cookie=False,
            force=False,
        )
    )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert result == 0
    assert PasswordHasher().verify(config["password_hash"], "x")


def test_reset_password_accepts_one_character_password(tmp_path, monkeypatch):
    config_path = tmp_path / "app-config.json"
    config_path.write_text(
        json.dumps(
            {
                "password_hash": PasswordHasher().hash("senha-anterior"),
                "secret_key": "s" * 64,
            }
        ),
        encoding="utf-8",
    )
    answers = iter(["1", "1"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    result = reset_password(Namespace(config_path=config_path))

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert result == 0
    assert PasswordHasher().verify(config["password_hash"], "1")
    assert config["secret_key"] != "s" * 64
