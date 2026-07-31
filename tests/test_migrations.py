from __future__ import annotations

import sqlite3

import pytest

import handball.database.migrations as migrations
from handball.database import AttendanceRepository
from handball.database.migrations import (
    DatabaseMigrator,
    DatabaseSchemaError,
    logical_fingerprint,
    verify_database,
)


def _domain_snapshot(database_path) -> dict[str, list[tuple[object, ...]]]:
    snapshot: dict[str, list[tuple[object, ...]]] = {}
    with sqlite3.connect(database_path) as conn:
        for table in sorted(migrations.DOMAIN_TABLES):
            rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            snapshot[table] = [tuple(row) for row in rows]
    return snapshot


def _make_unversioned_current(database_path) -> AttendanceRepository:
    repository = AttendanceRepository(database_path)
    repository.bootstrap()
    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP TABLE schema_migrations")
        conn.execute("PRAGMA user_version = 0")
    return repository


def _make_v5_database(database_path) -> None:
    AttendanceRepository(database_path).bootstrap()
    DatabaseMigrator(database_path).apply_pending(
        expected_fingerprint=logical_fingerprint(database_path),
        legacy_admin=("admin", "test-password-hash"),
        app_version="pytest-v5",
        origin="pytest",
    )


def _make_ea5404b_database(database_path) -> None:
    """Reproduz o DDL histórico de ea5404b, anterior a sync/version."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE team_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                position TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE training_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                training_date TEXT NOT NULL UNIQUE,
                notes TEXT NOT NULL DEFAULT '',
                is_finalized INTEGER NOT NULL DEFAULT 0
                    CHECK (is_finalized IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                confirmation_status TEXT NOT NULL DEFAULT 'PENDING',
                present INTEGER NULL CHECK (present IN (0, 1) OR present IS NULL),
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE (session_id, member_id),
                FOREIGN KEY (session_id) REFERENCES training_sessions(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (member_id) REFERENCES team_members(id)
                    ON DELETE RESTRICT
            );
            CREATE TABLE attendance_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                old_confirmation_status TEXT NULL,
                new_confirmation_status TEXT NULL,
                old_present INTEGER NULL,
                new_present INTEGER NULL,
                old_notes TEXT NULL,
                new_notes TEXT NULL,
                changed_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'ui',
                FOREIGN KEY (session_id) REFERENCES training_sessions(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (member_id) REFERENCES team_members(id)
                    ON DELETE RESTRICT
            );
            CREATE INDEX idx_attendance_session
                ON attendance_records(session_id);
            CREATE INDEX idx_audit_session_changed
                ON attendance_audit_log(session_id, changed_at);
            CREATE INDEX idx_training_date
                ON training_sessions(training_date);

            INSERT INTO team_members(
                id, name, position, active, created_at, updated_at
            ) VALUES (7, 'Atleta histórico', 'ARM', 0, '2026-01-01', '2026-01-02');
            INSERT INTO training_sessions(
                id, training_date, notes, is_finalized, created_at, updated_at
            ) VALUES (11, '2026-01-03', 'legado', 1, '2026-01-03', '2026-01-04');
            INSERT INTO attendance_records(
                id, session_id, member_id, confirmation_status,
                present, notes, updated_at
            ) VALUES (
                13, 11, 7, 'CONFIRMED_EARLY', 1, 'preservar', '2026-01-04'
            );
            INSERT INTO attendance_audit_log(
                id, session_id, member_id,
                old_confirmation_status, new_confirmation_status,
                old_present, new_present, old_notes, new_notes,
                changed_at, source
            ) VALUES (
                17, 11, 7, 'PENDING', 'CONFIRMED_EARLY',
                NULL, 1, '', 'preservar', '2026-01-04', 'ea5404b'
            );
            """
        )


def test_status_on_missing_database_is_read_only(tmp_path):
    database_path = tmp_path / "missing.db"

    status = DatabaseMigrator(database_path).status()

    assert status.state == "missing"
    assert status.current_version == 0
    assert not status.compatible
    assert status.problems
    assert not database_path.exists()


def test_bootstrap_creates_formally_versioned_current_schema(tmp_path):
    database_path = tmp_path / "new.db"
    AttendanceRepository(database_path).bootstrap()

    status = DatabaseMigrator(database_path).status()
    verification = verify_database(database_path)

    assert status.state == "migration_required"
    assert status.current_version == 1
    assert status.latest_version == 8
    assert status.pending_versions == (2, 3, 4, 5, 6, 7, 8)
    assert status.versioned and status.compatible
    assert verification["quick_check"] == "ok"
    assert verification["foreign_key_check"] == []
    assert verification["ok"] is True


def test_adopting_current_legacy_database_only_adds_version_metadata(tmp_path):
    database_path = tmp_path / "legacy-current.db"
    repository = _make_unversioned_current(database_path)
    member = repository.list_members()[0]
    repository.update_member(int(member["id"]), position="CUSTOM", active=False)
    before = _domain_snapshot(database_path)
    fingerprint = logical_fingerprint(database_path)

    before_status = DatabaseMigrator(database_path).status()
    result = DatabaseMigrator(database_path).apply_pending(
        app_version="test-release",
        origin="pytest",
        expected_fingerprint=fingerprint,
    )
    after = _domain_snapshot(database_path)

    assert before_status.state == "legacy_current"
    assert not before_status.versioned
    assert result.state == "migration_required"
    assert result.versioned and result.compatible
    assert after == before
    assert next(row for row in after["team_members"] if row[0] == member["id"])[2:4] == (
        "CUSTOM",
        0,
    )

    second_fingerprint = logical_fingerprint(database_path)
    second = DatabaseMigrator(database_path).apply_pending(
        app_version="test-release",
        origin="pytest",
        expected_fingerprint=second_fingerprint,
    )
    assert second.to_dict() == result.to_dict()


def test_legacy_column_upgrade_preserves_populated_rows(tmp_path):
    database_path = tmp_path / "legacy-v0.db"
    repository = _make_unversioned_current(database_path)
    session = repository.get_or_create_session("2026-07-30")
    before_records = repository.get_session_records(int(session["id"]))
    with sqlite3.connect(database_path) as conn:
        conn.execute("ALTER TABLE attendance_records DROP COLUMN version")

    status = DatabaseMigrator(database_path).status()
    assert status.state == "legacy_requires_migration"
    assert not status.compatible

    result = DatabaseMigrator(database_path).apply_pending(
        app_version="test-release",
        origin="pytest",
        expected_fingerprint=logical_fingerprint(database_path),
    )
    after_records = AttendanceRepository(database_path).get_session_records(
        int(session["id"])
    )

    assert result.current_version == 1
    assert [row["record_id"] for row in after_records] == [
        row["record_id"] for row in before_records
    ]
    assert all(row["version"] == 1 for row in after_records)


def test_ea5404b_legacy_is_canonical_and_adds_version_and_sync_without_data_loss(
    tmp_path,
):
    database_path = tmp_path / "ea5404b.db"
    _make_ea5404b_database(database_path)
    with sqlite3.connect(database_path) as conn:
        before = {
            "member": conn.execute("SELECT * FROM team_members").fetchone(),
            "session": conn.execute("SELECT * FROM training_sessions").fetchone(),
            "record": conn.execute("SELECT * FROM attendance_records").fetchone(),
            "audit": conn.execute("SELECT * FROM attendance_audit_log").fetchone(),
        }

    migrator = DatabaseMigrator(database_path)
    status = migrator.status()
    assert status.state == "legacy_requires_migration"
    assert status.problems == ()

    result = migrator.apply_pending(
        app_version="test-release",
        origin="pytest-ea5404b",
        expected_fingerprint=logical_fingerprint(database_path),
    )

    assert result.state == "migration_required"
    with sqlite3.connect(database_path) as conn:
        assert conn.execute("SELECT * FROM team_members").fetchone() == before["member"]
        assert (
            conn.execute("SELECT * FROM training_sessions").fetchone()
            == before["session"]
        )
        migrated_record = conn.execute(
            """
            SELECT id, session_id, member_id, confirmation_status,
                   present, notes, updated_at, version
            FROM attendance_records
            """
        ).fetchone()
        assert migrated_record[:-1] == before["record"]
        assert migrated_record[-1] == 1
        assert (
            conn.execute("SELECT * FROM attendance_audit_log").fetchone()
            == before["audit"]
        )
        assert conn.execute("SELECT COUNT(*) FROM sync_operations").fetchone()[0] == 0


def test_ea5404b_shape_with_noncanonical_constraint_is_rejected(tmp_path):
    database_path = tmp_path / "ea5404b-invalid.db"
    _make_ea5404b_database(database_path)
    with sqlite3.connect(database_path) as conn:
        conn.execute("DROP INDEX idx_training_date")

    status = DatabaseMigrator(database_path).status()

    assert status.state == "invalid"
    assert any("idx_training_date" in problem for problem in status.problems)


def test_migration_ddl_rolls_back_on_failure(tmp_path, monkeypatch):
    database_path = tmp_path / "rollback.db"
    repository = _make_unversioned_current(database_path)
    with sqlite3.connect(database_path) as conn:
        conn.execute("ALTER TABLE attendance_records DROP COLUMN version")

    original_apply = migrations._apply_schema_v1

    def fail_after_ddl(conn: sqlite3.Connection) -> None:
        original_apply(conn)
        raise RuntimeError("falha injetada")

    monkeypatch.setattr(migrations, "_apply_schema_v1", fail_after_ddl)
    with pytest.raises(RuntimeError, match="falha injetada"):
        DatabaseMigrator(database_path).apply_pending(
            app_version="test-release",
            origin="pytest",
            expected_fingerprint=logical_fingerprint(database_path),
        )

    with sqlite3.connect(database_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(attendance_records)")
        }
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    assert "version" not in columns
    assert "schema_migrations" not in tables
    assert user_version == 0


def test_changed_database_invalidates_expected_fingerprint(tmp_path):
    database_path = tmp_path / "changed.db"
    repository = _make_unversioned_current(database_path)
    expected = logical_fingerprint(database_path)
    member = repository.list_members()[0]
    repository.update_member(int(member["id"]), position="ALTERADA", active=True)

    with pytest.raises(DatabaseSchemaError, match="mudou depois do plano"):
        DatabaseMigrator(database_path).apply_pending(
            app_version="test-release",
            origin="pytest",
            expected_fingerprint=expected,
        )

    assert DatabaseMigrator(database_path).status().state == "legacy_current"


def test_fingerprint_is_rechecked_after_begin_immediate(tmp_path, monkeypatch):
    database_path = tmp_path / "race.db"
    repository = _make_unversioned_current(database_path)
    expected = logical_fingerprint(database_path)
    member_id = int(repository.list_members()[0]["id"])
    real_connect = sqlite3.connect
    injected = False

    def connect_with_race(*args, **kwargs):
        nonlocal injected
        conn = real_connect(*args, **kwargs)

        def trace(statement: str) -> None:
            nonlocal injected
            if statement.strip().upper() == "BEGIN IMMEDIATE" and not injected:
                injected = True
                with real_connect(database_path) as racing_connection:
                    racing_connection.execute(
                        "UPDATE team_members SET position = 'RACE' WHERE id = ?",
                        (member_id,),
                    )

        conn.set_trace_callback(trace)
        return conn

    monkeypatch.setattr(migrations.sqlite3, "connect", connect_with_race)
    with pytest.raises(DatabaseSchemaError, match="mudou depois do plano"):
        DatabaseMigrator(database_path).apply_pending(
            app_version="test-release",
            origin="pytest-race",
            expected_fingerprint=expected,
        )

    assert injected
    with real_connect(database_path) as conn:
        assert conn.execute(
            "SELECT position FROM team_members WHERE id = ?", (member_id,)
        ).fetchone()[0] == "RACE"
        assert conn.execute(
            "SELECT 1 FROM sqlite_schema WHERE name = 'schema_migrations'"
        ).fetchone() is None


def test_apply_requires_fingerprint_and_never_creates_database_or_directory(tmp_path):
    missing = tmp_path / "absent-parent" / "missing.db"
    with pytest.raises(DatabaseSchemaError, match="bootstrap explícito"):
        DatabaseMigrator(missing).apply_pending(expected_fingerprint="0" * 64)
    assert not missing.parent.exists()

    existing = tmp_path / "legacy.db"
    _make_unversioned_current(existing)
    with pytest.raises(DatabaseSchemaError, match="expected_fingerprint"):
        DatabaseMigrator(existing).apply_pending()
    assert DatabaseMigrator(existing).status().state == "legacy_current"


def test_literal_quick_check_failure_rolls_back_every_migration_step(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "quick-check-rollback.db"
    _make_ea5404b_database(database_path)
    original_fetchall = migrations._fetchall

    def nonliteral_quick_check(conn: sqlite3.Connection, sql: str):
        if sql == "PRAGMA quick_check":
            return [("ok",), ("resultado extra",)]
        return original_fetchall(conn, sql)

    monkeypatch.setattr(migrations, "_fetchall", nonliteral_quick_check)
    with pytest.raises(DatabaseSchemaError, match="quick_check"):
        DatabaseMigrator(database_path).apply_pending(
            app_version="test-release",
            origin="pytest-quick-check",
            expected_fingerprint=logical_fingerprint(database_path),
        )

    with sqlite3.connect(database_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(attendance_records)")
        }
        assert "sync_operations" not in tables
        assert "schema_migrations" not in tables
        assert "version" not in columns
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 0


def test_v1_checksum_covers_conditional_sql_and_canonical_contract():
    baseline = migrations.MIGRATION_V1_CHECKSUM
    reformatted_sql = migrations._migration_checksum(
        1,
        migrations.MIGRATION_V1_NAME,
        migrations.SCHEMA_V1_STATEMENTS,
        conditional_steps=(
            {
                "condition": "attendance_records.version is absent",
                "sql": migrations.SCHEMA_V1_ADD_VERSION_SQL + " ",
            },
        ),
        canonical_contract=migrations._canonical_schema_contract(),
    )
    changed_sql = migrations._migration_checksum(
        1,
        migrations.MIGRATION_V1_NAME,
        migrations.SCHEMA_V1_STATEMENTS,
        conditional_steps=(
            {
                "condition": "attendance_records.version is absent",
                "sql": migrations.SCHEMA_V1_ADD_VERSION_SQL.replace(
                    "DEFAULT 1", "DEFAULT 2"
                ),
            },
        ),
        canonical_contract=migrations._canonical_schema_contract(),
    )
    changed_contract = migrations._canonical_schema_contract()
    changed_contract["recognized_unversioned_layouts"] = []
    changed_contract_checksum = migrations._migration_checksum(
        1,
        migrations.MIGRATION_V1_NAME,
        migrations.SCHEMA_V1_STATEMENTS,
        conditional_steps=migrations.SCHEMA_V1_CONDITIONAL_STEPS,
        canonical_contract=changed_contract,
    )

    # Espaço muda somente a forma, não o SQL normalizado.
    assert reformatted_sql == baseline
    assert changed_sql != baseline
    assert changed_contract_checksum != baseline


def test_fingerprint_covers_migration_ledger_and_user_version(tmp_path):
    database_path = tmp_path / "metadata.db"
    AttendanceRepository(database_path).bootstrap()
    before = logical_fingerprint(database_path)

    with sqlite3.connect(database_path) as conn:
        conn.execute(
            "UPDATE schema_migrations SET origin = 'altered' WHERE version = 1"
        )
    after_ledger = logical_fingerprint(database_path)

    with sqlite3.connect(database_path) as conn:
        conn.execute("PRAGMA user_version = 0")
    after_version = logical_fingerprint(database_path)

    assert after_ledger != before
    assert after_version != after_ledger


def test_status_rejects_matching_columns_without_required_constraints(tmp_path):
    database_path = tmp_path / "loose-constraints.db"
    repository = AttendanceRepository(database_path)
    repository.bootstrap()
    session = repository.get_or_create_session("2026-08-02")
    records_before = repository.get_session_records(int(session["id"]))

    with sqlite3.connect(database_path) as conn:
        conn.executescript(
            """
            ALTER TABLE attendance_records RENAME TO attendance_records_old;

            CREATE TABLE attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                confirmation_status TEXT NOT NULL DEFAULT 'PENDING',
                present INTEGER NULL,
                notes TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );

            INSERT INTO attendance_records(
                id, session_id, member_id, confirmation_status,
                present, notes, version, updated_at
            )
            SELECT
                id, session_id, member_id, confirmation_status,
                present, notes, version, updated_at
            FROM attendance_records_old;

            DROP TABLE attendance_records_old;
            CREATE INDEX idx_attendance_session
                ON attendance_records(session_id);
            """
        )

    status = DatabaseMigrator(database_path).status()

    assert status.state == "invalid"
    assert status.compatible is False
    assert any("UNIQUE" in problem for problem in status.problems)
    assert any("Chaves estrangeiras" in problem for problem in status.problems)
    assert any("CHECK" in problem for problem in status.problems)
    with pytest.raises(RuntimeError, match="incompatível"):
        repository.validate_existing(quick_check=True)
    with sqlite3.connect(database_path) as conn:
        assert int(
            conn.execute("SELECT COUNT(*) FROM attendance_records").fetchone()[0]
        ) == len(records_before)


@pytest.mark.parametrize(
    "tamper_sql",
    (
        "DROP INDEX idx_user_permission_grants_actor",
        """
        DROP INDEX idx_user_permission_grants_actor;
        ALTER TABLE user_permission_grants RENAME TO grants_old;
        CREATE TABLE user_permission_grants (
            user_id INTEGER NOT NULL,
            permission_code TEXT NOT NULL,
            granted_by_user_id INTEGER NOT NULL,
            granted_at TEXT NOT NULL,
            extra TEXT,
            PRIMARY KEY(user_id,permission_code),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(granted_by_user_id) REFERENCES users(id) ON DELETE RESTRICT
        );
        DROP TABLE grants_old;
        CREATE INDEX idx_user_permission_grants_actor
            ON user_permission_grants(granted_by_user_id,granted_at);
        """,
        """
        DROP INDEX idx_user_permission_grants_actor;
        ALTER TABLE user_permission_grants RENAME TO grants_old;
        CREATE TABLE user_permission_grants (
            user_id INTEGER NOT NULL,
            permission_code TEXT NOT NULL
                CHECK(permission_code IN('sql.explore','sql.admin')),
            granted_by_user_id INTEGER NOT NULL,
            granted_at TEXT NOT NULL,
            PRIMARY KEY(user_id,permission_code),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY(granted_by_user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        DROP TABLE grants_old;
        CREATE UNIQUE INDEX idx_user_permission_grants_actor
            ON user_permission_grants(granted_by_user_id,granted_at);
        """,
    ),
)
def test_v5_contract_rejects_permission_grant_tampering(tmp_path, tamper_sql):
    database_path = tmp_path / "v5-tampered.db"
    _make_v5_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.executescript(tamper_sql)
    status = DatabaseMigrator(database_path).status()
    assert status.compatible is False
    assert status.state == "invalid"
    assert status.problems
