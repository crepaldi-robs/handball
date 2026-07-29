from __future__ import annotations

import hashlib
import json
import sqlite3
from argparse import Namespace

from argon2 import PasswordHasher
import pytest

from handball.database.cli import (
    backup,
    database_plan,
    database_status,
    fingerprint_database,
    initialize,
    initialize_database,
    migrate_database,
    release_contract,
    reset_password,
    verify_database,
)
from handball.database import DatabaseCompatibilityError, AttendanceRepository
from handball.database.migrations import (
    FINGERPRINT_FORMAT,
    MAX_SUPPORTED_SCHEMA_VERSION,
    MIGRATION_V1_CHECKSUM,
    MIGRATION_V1_NAME,
    MIN_SUPPORTED_SCHEMA_VERSION,
    DatabaseMigrator,
    logical_fingerprint,
)


def test_release_contract_is_read_only_and_exposes_schema_range(
    capsys,
    monkeypatch,
):
    monkeypatch.setattr(
        "handball.database.cli.AttendanceRepository",
        lambda *_args, **_kwargs: pytest.fail(
            "release-contract não deve instanciar o repositório"
        ),
    )

    assert release_contract(Namespace()) == 0

    assert json.loads(capsys.readouterr().out) == {
        "format": 1,
        "schema_compatibility": {
            "minimum": MIN_SUPPORTED_SCHEMA_VERSION,
            "maximum": MAX_SUPPORTED_SCHEMA_VERSION,
        },
    }


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


def test_database_bootstrap_verify_and_explicit_backup_are_separate(
    tmp_path, capsys
):
    database_path = tmp_path / "data" / "presencas.db"
    backup_dir = tmp_path / "backups"
    config_path = tmp_path / "data" / "app-config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "db_path": str(database_path),
                "backup_dir": str(backup_dir),
            }
        ),
        encoding="utf-8",
    )

    assert initialize_database(Namespace(config_path=config_path)) == 0
    capsys.readouterr()
    repository = AttendanceRepository(database_path)
    member = repository.list_members()[0]
    repository.update_member(int(member["id"]), position="PERSONALIZADA", active=False)

    assert verify_database(Namespace(config_path=config_path)) == 0
    assert capsys.readouterr().out.strip() == "ok"
    assert fingerprint_database(Namespace(config_path=config_path)) == 0
    source_fingerprint = capsys.readouterr().out.strip()
    assert len(source_fingerprint) == 64

    destination = backup_dir / "update-test.db"
    assert backup(
        Namespace(
            config_path=config_path,
            destination=destination,
            keep=30,
        )
    ) == 0
    assert capsys.readouterr().out.strip() == str(destination)

    original_member = next(
        item for item in repository.list_members() if item["id"] == member["id"]
    )
    backup_member = next(
        item
        for item in AttendanceRepository(destination).list_members()
        if item["id"] == member["id"]
    )
    assert (original_member["position"], original_member["active"]) == (
        "PERSONALIZADA",
        0,
    )
    assert backup_member == original_member
    assert AttendanceRepository(destination).logical_fingerprint() == source_fingerprint


def test_verify_database_does_not_create_missing_file(tmp_path):
    database_path = tmp_path / "missing.db"
    config_path = tmp_path / "app-config.json"
    config_path.write_text(
        json.dumps(
            {
                "db_path": str(database_path),
                "backup_dir": str(tmp_path / "backups"),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatabaseCompatibilityError, match="não encontrado"):
        verify_database(Namespace(config_path=config_path))

    assert not database_path.exists()


def test_database_plan_requires_bootstrap_for_missing_database(tmp_path, capsys):
    database_path = tmp_path / "missing-parent" / "missing.db"
    config_path = tmp_path / "app-config.json"
    config_path.write_text(
        json.dumps(
            {
                "db_path": str(database_path),
                "backup_dir": str(tmp_path / "backups"),
            }
        ),
        encoding="utf-8",
    )

    exit_code = database_plan(Namespace(config_path=config_path))
    plan = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert plan["action"] == "bootstrap-required"
    assert plan["fingerprint_format"] == FINGERPRINT_FORMAT
    assert plan["logical_fingerprint"] is None
    assert plan["problems"]
    assert plan["migration_manifest"][0] == {
        "version": 1,
        "name": MIGRATION_V1_NAME,
        "checksum_sha256": MIGRATION_V1_CHECKSUM,
        "action": "bootstrap-required",
    }
    assert plan["migration_manifest"][1]["version"] == 2
    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_explicit_backup_must_stay_inside_configured_directory(tmp_path):
    database_path = tmp_path / "data" / "presencas.db"
    backup_dir = tmp_path / "backups"
    config_path = tmp_path / "app-config.json"
    AttendanceRepository(database_path).bootstrap()
    config_path.write_text(
        json.dumps(
            {
                "db_path": str(database_path),
                "backup_dir": str(backup_dir),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="deve permanecer"):
        backup(
            Namespace(
                config_path=config_path,
                destination=tmp_path / "fora.db",
                keep=30,
            )
        )

    assert not (tmp_path / "fora.db").exists()


def test_database_migration_requires_confirmed_plan_and_verified_backup(
    tmp_path, capsys
):
    database_path = tmp_path / "data" / "presencas.db"
    backup_dir = tmp_path / "backups"
    config_path = tmp_path / "app-config.json"
    AttendanceRepository(database_path).bootstrap()
    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP TABLE schema_migrations")
        conn.execute("PRAGMA user_version = 0")
    config_path.write_text(
        json.dumps(
            {
                "db_path": str(database_path),
                "backup_dir": str(backup_dir),
                "admin_username": "bob",
                "password_hash": PasswordHasher().hash("senha-bob"),
            }
        ),
        encoding="utf-8",
    )

    assert database_plan(Namespace(config_path=config_path)) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["action"] == "adopt-baseline"
    assert plan["migration_manifest"][0] == {
        "version": 1,
        "name": MIGRATION_V1_NAME,
        "checksum_sha256": MIGRATION_V1_CHECKSUM,
        "action": "adopt-baseline",
    }
    assert plan["migration_manifest"][1]["version"] == 2
    canonical_plan = dict(plan)
    plan_sha256 = canonical_plan.pop("plan_sha256")
    assert plan_sha256 == hashlib.sha256(
        json.dumps(
            canonical_plan,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    common = {
        "config_path": config_path,
        "apply": True,
        "expected_plan_sha256": plan["plan_sha256"],
        "expected_fingerprint": plan["logical_fingerprint"],
        "app_version": "pytest-release",
    }
    with pytest.raises(SystemExit, match="--backup-path é obrigatório"):
        migrate_database(Namespace(**common, backup_path=""))

    backup_path = backup_dir / "pre-migration.db"
    assert migrate_database(
        Namespace(**common, backup_path=backup_path)
    ) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == "applied"
    assert result["schema"]["current_version"] == 5
    assert result["verification"]["quick_check"] == "ok"
    assert result["verification"]["foreign_key_check"] == []
    assert backup_path.is_file()
    assert len(result["backup_sha256"]) == 64


def test_database_migration_backs_up_recognized_legacy_before_column_upgrade(
    tmp_path, capsys
):
    database_path = tmp_path / "data" / "presencas.db"
    backup_dir = tmp_path / "backups"
    config_path = tmp_path / "app-config.json"
    repository = AttendanceRepository(database_path)
    repository.bootstrap()
    session = repository.get_or_create_session("2026-08-01")
    records_before = repository.get_session_records(int(session["id"]))

    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP TABLE schema_migrations")
        conn.execute("PRAGMA user_version = 0")
        conn.execute("ALTER TABLE attendance_records DROP COLUMN version")
    config_path.write_text(
        json.dumps(
            {
                "db_path": str(database_path),
                "backup_dir": str(backup_dir),
                "admin_username": "bob",
                "password_hash": PasswordHasher().hash("senha-bob"),
            }
        ),
        encoding="utf-8",
    )

    assert database_plan(Namespace(config_path=config_path)) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["action"] == "migrate"
    assert plan["problems"] == []

    backup_path = backup_dir / "legacy-before-v1.db"
    assert migrate_database(
        Namespace(
            config_path=config_path,
            apply=True,
            expected_plan_sha256=plan["plan_sha256"],
            expected_fingerprint=plan["logical_fingerprint"],
            backup_path=backup_path,
            app_version="pytest-release",
        )
    ) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == "applied"
    assert logical_fingerprint(backup_path) == plan["logical_fingerprint"]
    assert DatabaseMigrator(backup_path).status().state == "legacy_requires_migration"
    assert DatabaseMigrator(database_path).status().state == "current"
    with sqlite3.connect(backup_path) as conn:
        backup_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(attendance_records)")
        }
        backup_record_count = int(
            conn.execute("SELECT COUNT(*) FROM attendance_records").fetchone()[0]
        )
    assert "version" not in backup_columns
    assert backup_record_count == len(records_before)
    assert not list(backup_dir.glob(".*.partial"))


def test_database_status_returns_nonzero_for_incompatible_schema(tmp_path, capsys):
    database_path = tmp_path / "data" / "presencas.db"
    config_path = tmp_path / "app-config.json"
    AttendanceRepository(database_path).bootstrap()
    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP TABLE schema_migrations")
        conn.execute("PRAGMA user_version = 0")
        conn.execute("ALTER TABLE attendance_records DROP COLUMN version")
    config_path.write_text(
        json.dumps(
            {
                "db_path": str(database_path),
                "backup_dir": str(tmp_path / "backups"),
            }
        ),
        encoding="utf-8",
    )

    exit_code = database_status(Namespace(config_path=config_path))
    payload = json.loads(capsys.readouterr().out)

    assert payload["verification"]["ok"] is True
    assert payload["schema"]["compatible"] is False
    assert payload["schema"]["state"] == "legacy_requires_migration"
    assert exit_code == 2
