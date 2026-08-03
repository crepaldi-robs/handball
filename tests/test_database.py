from __future__ import annotations

import sqlite3

import pytest

from handball.database import (
    DatabaseCompatibilityError,
    AttendanceRepository,
)


def test_initialization_and_audit(tmp_path):
    repo = AttendanceRepository(tmp_path / "test.db")
    repo.bootstrap()

    members = repo.list_members(include_inactive=False)
    assert len(members) == 19

    session = repo.get_or_create_session("2026-07-21")
    session_id = int(session["id"])
    records = repo.get_session_records(session_id)
    assert len(records) == 19
    names = [record["name"] for record in records]
    assert names == sorted(names, key=str.casefold)

    first = records[0]
    changed = repo.save_records(
        session_id,
        [
            {
                "member_id": first["member_id"],
                "confirmation_status": "CONFIRMED_EARLY",
                "present": True,
                "notes": "Teste",
            }
        ],
        source="pytest",
    )
    assert changed == 1

    refreshed = repo.get_session_records(session_id)
    updated = next(
        row for row in refreshed if row["member_id"] == first["member_id"]
    )
    assert updated["confirmation_status"] == "CONFIRMED_EARLY"
    assert updated["present"] == 1
    assert updated["notes"] == "Teste"

    audit = repo.get_audit_log()
    assert len(audit) == 1
    entry = audit[0]
    assert entry["source"] == "pytest"
    assert entry["old_confirmation_status"] == "PENDING"
    assert entry["new_confirmation_status"] == "CONFIRMED_EARLY"
    assert entry["old_present"] is None
    assert entry["new_present"] == 1
    assert entry["old_notes"] == ""
    assert entry["new_notes"] == "Teste"


def test_finalize_marks_unchecked_as_absent(tmp_path):
    repo = AttendanceRepository(tmp_path / "test.db")
    repo.bootstrap()
    session = repo.get_or_create_session("2026-07-22")
    session_id = int(session["id"])

    changed = repo.finalize_session(session_id, source="pytest-finalize")
    assert changed == 19

    records = repo.get_session_records(session_id)
    assert all(record["present"] == 0 for record in records)
    assert repo.get_session(session_id)["is_finalized"] == 1


def test_existing_database_is_validated_without_seed_or_data_changes(tmp_path):
    repo = AttendanceRepository(tmp_path / "persistent.db")
    repo.bootstrap()
    member = repo.list_members()[0]
    repo.update_member(int(member["id"]), position="TESTE", active=False)

    with repo.read_only_connection() as conn:
        before = tuple(
            tuple(row)
            for row in conn.execute(
                "SELECT id, name, position, active, created_at, updated_at "
                "FROM team_members ORDER BY id"
            )
        )
    fingerprint_before = repo.logical_fingerprint()

    assert repo.validate_existing() == 1
    repo.validate_existing()

    with repo.read_only_connection() as conn:
        after = tuple(
            tuple(row)
            for row in conn.execute(
                "SELECT id, name, position, active, created_at, updated_at "
                "FROM team_members ORDER BY id"
            )
        )

    assert after == before
    assert repo.logical_fingerprint() == fingerprint_before
    changed = next(row for row in after if row[0] == member["id"])
    assert changed[2:4] == ("TESTE", 0)


def test_validation_fails_closed_when_database_is_missing(tmp_path):
    database_path = tmp_path / "missing.db"
    repo = AttendanceRepository(database_path)

    with pytest.raises(DatabaseCompatibilityError, match="não encontrado"):
        repo.validate_existing()

    assert not database_path.exists()


def test_bootstrap_failure_is_retry_safe_and_leaves_no_partial_database(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "data" / "retry.db"
    repository = AttendanceRepository(database_path)
    original_seed = AttendanceRepository.seed_initial_members
    attempts = 0

    def fail_first_candidate_seed(self):
        nonlocal attempts
        if ".bootstrap.partial" in self.db_path.name:
            attempts += 1
            original_seed(self)
            if attempts == 1:
                raise RuntimeError("falha de seed injetada")
            return None
        return original_seed(self)

    monkeypatch.setattr(
        AttendanceRepository,
        "seed_initial_members",
        fail_first_candidate_seed,
    )

    with pytest.raises(RuntimeError, match="falha de seed injetada"):
        repository.bootstrap()
    assert not database_path.exists()
    assert not list(database_path.parent.glob("*.bootstrap.partial*"))

    repository.bootstrap()

    assert repository.validate_existing(quick_check=True) == 1
    assert len(repository.list_members()) == 19
    assert attempts == 2
    assert not list(database_path.parent.glob("*.bootstrap.partial*"))


def test_repository_fingerprint_covers_contents_of_every_user_table(tmp_path):
    database_path = tmp_path / "all-tables.db"
    repository = AttendanceRepository(database_path)
    repository.bootstrap()
    before_extra_table = repository.logical_fingerprint()

    with sqlite3.connect(database_path) as conn:
        conn.execute("CREATE TABLE future_extension (key TEXT PRIMARY KEY, value TEXT)")
    after_create = repository.logical_fingerprint()

    with sqlite3.connect(database_path) as conn:
        conn.execute(
            "INSERT INTO future_extension(key, value) VALUES ('feature', 'v1')"
        )
    after_insert = repository.logical_fingerprint()

    with sqlite3.connect(database_path) as conn:
        conn.execute(
            "UPDATE future_extension SET value = 'v2' WHERE key = 'feature'"
        )
    after_update = repository.logical_fingerprint()

    assert len({before_extra_table, after_create, after_insert, after_update}) == 4


def test_existing_legacy_schema_is_not_migrated_implicitly(tmp_path):
    database_path = tmp_path / "legacy.db"
    repo = AttendanceRepository(database_path)
    repo.bootstrap()

    with sqlite3.connect(database_path) as conn:
        conn.execute("ALTER TABLE attendance_records DROP COLUMN version")

    with pytest.raises(DatabaseCompatibilityError, match="version"):
        repo.validate_existing()

    with sqlite3.connect(database_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(attendance_records)")
        }
    assert "version" not in columns


def test_common_backup_rejects_schema_that_requires_explicit_migration(tmp_path):
    database_path = tmp_path / "legacy.db"
    destination = tmp_path / "backups" / "legacy-copy.db"
    repo = AttendanceRepository(database_path)
    repo.bootstrap()

    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP TABLE schema_migrations")
        conn.execute("PRAGMA user_version = 0")
        conn.execute("ALTER TABLE attendance_records DROP COLUMN version")

    with pytest.raises(DatabaseCompatibilityError, match="version"):
        repo.backup_to(destination)

    assert not destination.exists()
    assert not list(destination.parent.glob(".*.partial"))


def test_validation_rejects_missing_required_index_without_repairing_it(tmp_path):
    database_path = tmp_path / "missing-index.db"
    repo = AttendanceRepository(database_path)
    repo.bootstrap()

    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP INDEX idx_attendance_session")

    with pytest.raises(DatabaseCompatibilityError, match="Índice obrigatório"):
        repo.validate_existing(quick_check=True)

    with sqlite3.connect(database_path) as conn:
        index = conn.execute(
            "SELECT 1 FROM sqlite_schema "
            "WHERE type = 'index' AND name = 'idx_attendance_session'"
        ).fetchone()
    assert index is None


def test_backup_refuses_missing_source_without_creating_files(tmp_path):
    source = tmp_path / "missing.db"
    destination = tmp_path / "backups" / "copy.db"

    with pytest.raises(DatabaseCompatibilityError, match="não encontrado"):
        AttendanceRepository(source).backup_to(destination)

    assert not source.exists()
    assert not destination.exists()
