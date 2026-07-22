from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from handball.database import (
    MIGRATION_V1_CHECKSUM,
    DatabaseCompatibilityError,
    DatabaseManager,
    UnitOfWorkFactory,
)


EXPECTED_SCHEMA_V1_CHECKSUM = (
    "0369209bf3d35a2b752f2041a050c26861946bd6b3599831a398d5af6f5da821"
)


def test_manager_bootstrap_preserves_schema_v1_and_enables_wal(tmp_path: Path):
    manager = DatabaseManager(tmp_path / "data" / "presencas.db")

    manager.bootstrap()

    assert MIGRATION_V1_CHECKSUM == EXPECTED_SCHEMA_V1_CHECKSUM
    assert manager.validate_existing(quick_check=True) == 1
    with manager.read_only_connection() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_manager_never_creates_missing_database_during_regular_use(tmp_path: Path):
    database_path = tmp_path / "missing" / "presencas.db"
    manager = DatabaseManager(database_path)

    with pytest.raises(DatabaseCompatibilityError, match="não encontrado"):
        with manager.unit_of_work():
            pass

    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_unit_of_work_commits_and_rolls_back_all_repository_writes(tmp_path: Path):
    manager = DatabaseManager(tmp_path / "presencas.db")
    manager.bootstrap()
    factory = UnitOfWorkFactory(manager)

    with pytest.raises(RuntimeError, match="falha injetada"):
        with factory() as unit_of_work:
            unit_of_work.attendance.add_member("Rollback", "PD")
            unit_of_work.attendance.add_member("Rollback 2", "PE")
            raise RuntimeError("falha injetada")

    assert all(
        not member["name"].startswith("Rollback")
        for member in manager.attendance_repository().list_members()
    )

    with factory() as unit_of_work:
        unit_of_work.attendance.add_member("Commit", "PD")
        unit_of_work.attendance.add_member("Commit 2", "PE")

    names = {
        member["name"] for member in manager.attendance_repository().list_members()
    }
    assert {"Commit", "Commit 2"} <= names


def test_read_only_unit_of_work_reuses_query_only_connection(tmp_path: Path):
    manager = DatabaseManager(tmp_path / "presencas.db")
    manager.bootstrap()
    factory = UnitOfWorkFactory(manager)
    session = manager.attendance_repository().get_or_create_session("2026-07-22")

    with factory(read_only=True) as unit_of_work:
        assert len(unit_of_work.attendance.list_members()) == 19
        assert len(
            unit_of_work.attendance.get_session_records(int(session["id"]))
        ) == 19
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            unit_of_work.attendance.add_member("Proibido", "PD")

    assert all(
        member["name"] != "Proibido"
        for member in manager.attendance_repository().list_members()
    )


def test_backup_provider_hides_root_and_rejects_path_traversal(tmp_path: Path):
    manager = DatabaseManager(
        tmp_path / "presencas.db",
        backup_dir=tmp_path / "backups",
    )
    manager.bootstrap()

    backup = manager.create_backup("presencas-test.db")

    assert backup == tmp_path / "backups" / "presencas-test.db"
    assert backup.is_file()
    with pytest.raises(ValueError, match="arquivo .db simples"):
        manager.create_backup("../escape.db")

    download = manager.create_backup_download()
    assert download.filename.startswith("presencas-")
    assert download.content_length > 0
    assert sum(map(len, download.iter_bytes(chunk_size=1024))) == download.content_length
