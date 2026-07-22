from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from attendance.migrations import logical_fingerprint


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUARD_SCRIPT = PROJECT_ROOT / "scripts" / "database-guard.py"
STDLIB_IMPORTS = {
    "__future__",
    "argparse",
    "hashlib",
    "json",
    "os",
    "re",
    "sqlite3",
    "stat",
    "sys",
    "pathlib",
    "typing",
    "uuid",
}


def _write_config(
    config_path: Path,
    database_path: Path,
    *,
    backup_dir: Path | None = None,
) -> None:
    payload = {
        "admin_username": "operador-sensivel",
        "db_path": str(database_path.resolve()),
        "password_hash": "hash-super-secreto",
        "secret_key": "segredo-que-nao-pode-vazar",
    }
    if backup_dir is not None:
        payload["backup_dir"] = str(backup_dir.resolve())
    config_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _create_database(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            PRAGMA user_version = 7;
            CREATE TABLE arbitrary_domain_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                payload BLOB,
                optional_value TEXT
            );
            INSERT INTO arbitrary_domain_table(label, payload, optional_value)
            VALUES ('inicial', X'00FF', NULL);
            """
        )


def _run_guard(*arguments: object) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(GUARD_SCRIPT),
            *(str(item) for item in arguments),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _success_payload(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["format"] == "crepaldi-handball-database-guard/v1"
    assert payload["fingerprint_format"] == "crepaldi-handball-logical-sqlite/v1"
    return payload


def _error_payload(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert completed.returncode != 0
    assert completed.stdout == ""
    payload = json.loads(completed.stderr)
    assert payload["ok"] is False
    return payload


def _fingerprint(config_path: Path) -> str:
    payload = _success_payload(
        _run_guard("fingerprint", "--config-path", config_path)
    )
    fingerprint = str(payload["logical_fingerprint"])
    assert len(fingerprint) == 64
    return fingerprint


def test_application_and_operational_guard_share_fingerprint_contract(tmp_path: Path):
    database_path = tmp_path / "shared-contract.db"
    config_path = tmp_path / "app-config.json"
    _create_database(database_path)
    _write_config(config_path, database_path)

    assert logical_fingerprint(database_path) == _fingerprint(config_path)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _partial_files(destination: Path) -> list[Path]:
    return list(destination.parent.glob(f".{destination.name}.*.partial*"))


def _create_directory_reparse(link: Path, target: Path) -> str:
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"Criação de symlink indisponível: {symlink_error}")
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(
                "Criação de junction indisponível: "
                + completed.stdout
                + completed.stderr
            )
        return "junction"


def _remove_directory_reparse(link: Path, kind: str) -> None:
    if not os.path.lexists(link):
        return
    if kind == "junction":
        os.rmdir(link)
    else:
        link.unlink()


def test_guard_is_stdlib_only_and_never_imports_application_package():
    source = GUARD_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots <= STDLIB_IMPORTS
    assert "attendance" not in imported_roots


def test_guard_connection_is_uri_read_only_and_query_only(tmp_path: Path):
    database_path = tmp_path / "read-only.db"
    _create_database(database_path)
    source = GUARD_SCRIPT.read_text(encoding="utf-8")
    assert '?mode=ro' in source

    spec = importlib.util.spec_from_file_location("database_guard_test", GUARD_SCRIPT)
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    connection = guard._open_read_only(database_path)
    try:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute(
                "INSERT INTO arbitrary_domain_table(label) VALUES ('bloqueado')"
            )
    finally:
        connection.close()

    with sqlite3.connect(database_path) as verification:
        assert verification.execute(
            "SELECT COUNT(*) FROM arbitrary_domain_table"
        ).fetchone()[0] == 1


@pytest.mark.parametrize("command", ["verify", "fingerprint"])
def test_missing_config_fails_without_creating_any_file(tmp_path: Path, command: str):
    missing_config = tmp_path / "missing-config.json"

    result = _run_guard(command, "--config-path", missing_config)

    payload = _error_payload(result)
    assert payload["error"]["code"] == "config_missing"
    assert list(tmp_path.iterdir()) == []


def test_missing_database_fails_and_backup_does_not_create_destination(tmp_path: Path):
    database_path = tmp_path / "missing.db"
    config_path = tmp_path / "app-config.json"
    destination = tmp_path / "backups" / "copy.db"
    _write_config(config_path, database_path)

    verify = _run_guard("verify", "--config-path", config_path)
    backup = _run_guard(
        "backup",
        "--config-path",
        config_path,
        "--destination",
        destination,
    )

    assert _error_payload(verify)["error"]["code"] == "database_missing"
    assert _error_payload(backup)["error"]["code"] == "database_missing"
    assert not database_path.exists()
    assert not destination.exists()
    assert not destination.parent.exists()


@pytest.mark.parametrize("command", ["verify", "fingerprint"])
def test_expected_database_path_binds_every_read_operation(
    tmp_path: Path,
    command: str,
):
    database_path = tmp_path / "expected.db"
    other_database = tmp_path / "other.db"
    config_path = tmp_path / "app-config.json"
    _create_database(database_path)
    _create_database(other_database)
    _write_config(config_path, database_path)

    accepted = _run_guard(
        command,
        "--config-path",
        config_path,
        "--expected-database-path",
        database_path,
    )
    rejected = _run_guard(
        command,
        "--config-path",
        config_path,
        "--expected-database-path",
        other_database,
    )

    _success_payload(accepted)
    payload = _error_payload(rejected)
    assert payload["error"]["code"] == "database_path_mismatch"
    assert str(database_path) not in rejected.stderr
    assert str(other_database) not in rejected.stderr


def test_backup_is_bound_to_configured_expected_root_and_destination(tmp_path: Path):
    database_path = tmp_path / "source.db"
    config_path = tmp_path / "app-config.json"
    backup_root = tmp_path / "backups"
    wrong_root = tmp_path / "wrong-backups"
    backup_root.mkdir()
    wrong_root.mkdir()
    _create_database(database_path)
    _write_config(config_path, database_path, backup_dir=backup_root)

    accepted_destination = backup_root / "accepted.db"
    accepted = _run_guard(
        "backup",
        "--config-path",
        config_path,
        "--expected-database-path",
        database_path,
        "--expected-backup-root",
        backup_root,
        "--destination",
        accepted_destination,
    )
    accepted_payload = _success_payload(accepted)
    assert accepted_payload["destination"] == str(accepted_destination.resolve())

    outside_destination = tmp_path / "outside.db"
    outside = _run_guard(
        "backup",
        "--config-path",
        config_path,
        "--expected-database-path",
        database_path,
        "--expected-backup-root",
        backup_root,
        "--destination",
        outside_destination,
    )
    outside_payload = _error_payload(outside)
    assert outside_payload["error"]["code"] == "backup_destination_outside_root"
    assert not outside_destination.exists()

    wrong_root_destination = wrong_root / "wrong.db"
    wrong_root_result = _run_guard(
        "backup",
        "--config-path",
        config_path,
        "--expected-database-path",
        database_path,
        "--expected-backup-root",
        wrong_root,
        "--destination",
        wrong_root_destination,
    )
    wrong_root_payload = _error_payload(wrong_root_result)
    assert wrong_root_payload["error"]["code"] == "backup_root_mismatch"
    assert not wrong_root_destination.exists()


def test_symlinked_config_and_database_parent_are_refused(tmp_path: Path):
    real_database_root = tmp_path / "real-database"
    real_config_root = tmp_path / "real-config"
    real_database_root.mkdir()
    real_config_root.mkdir()
    database_path = real_database_root / "source.db"
    _create_database(database_path)
    real_config = real_config_root / "app-config.json"
    _write_config(real_config, database_path)

    linked_config_root = tmp_path / "linked-config-root"
    linked_database_root = tmp_path / "linked-database-root"
    config_link_kind = _create_directory_reparse(linked_config_root, real_config_root)
    database_link_kind = _create_directory_reparse(
        linked_database_root,
        real_database_root,
    )
    try:
        linked_config = linked_config_root / real_config.name
        config_result = _run_guard("verify", "--config-path", linked_config)
        config_payload = _error_payload(config_result)
        assert config_payload["error"]["code"] == "unsafe_config_path"

        indirect_config = tmp_path / "indirect-config.json"
        indirect_config.write_text(
            json.dumps({"db_path": str(linked_database_root / database_path.name)}),
            encoding="utf-8",
        )
        database_result = _run_guard("verify", "--config-path", indirect_config)
        database_payload = _error_payload(database_result)
        assert database_payload["error"]["code"] == "unsafe_database_path"
    finally:
        _remove_directory_reparse(linked_config_root, config_link_kind)
        _remove_directory_reparse(linked_database_root, database_link_kind)


def test_symlinked_backup_parent_is_refused_before_file_creation(tmp_path: Path):
    database_path = tmp_path / "source.db"
    real_backup_root = tmp_path / "real-backups"
    linked_backup_root = tmp_path / "linked-backups"
    config_path = tmp_path / "app-config.json"
    real_backup_root.mkdir()
    _create_database(database_path)
    link_kind = _create_directory_reparse(linked_backup_root, real_backup_root)
    config_path.write_text(
        json.dumps(
            {
                "db_path": str(database_path),
                "backup_dir": str(linked_backup_root),
            }
        ),
        encoding="utf-8",
    )

    destination = linked_backup_root / "copy.db"
    try:
        result = _run_guard(
            "backup",
            "--config-path",
            config_path,
            "--expected-database-path",
            database_path,
            "--expected-backup-root",
            linked_backup_root,
            "--destination",
            destination,
        )

        payload = _error_payload(result)
        assert payload["error"]["code"] in {
            "unsafe_backup_destination",
            "unsafe_backup_root",
        }
        assert not (real_backup_root / "copy.db").exists()
    finally:
        _remove_directory_reparse(linked_backup_root, link_kind)


def test_verify_is_exact_and_json_does_not_expose_config_or_paths(tmp_path: Path):
    database_path = tmp_path / "valid.db"
    config_path = tmp_path / "app-config.json"
    _create_database(database_path)
    _write_config(config_path, database_path)

    result = _run_guard("verify", "--config-path", config_path)
    payload = _success_payload(result)

    assert payload["quick_check"] == "ok"
    assert payload["quick_check_rows"] == ["ok"]
    assert payload["foreign_key_check"] == []
    assert payload["command"] == "verify"
    serialized = result.stdout
    assert "hash-super-secreto" not in serialized
    assert "segredo-que-nao-pode-vazar" not in serialized
    assert str(database_path) not in serialized
    assert str(config_path) not in serialized


def test_fingerprint_covers_user_version_schema_every_user_table_and_sequence(
    tmp_path: Path,
):
    database_path = tmp_path / "coverage.db"
    config_path = tmp_path / "app-config.json"
    _create_database(database_path)
    _write_config(config_path, database_path)
    initial = _fingerprint(config_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE future_feature(value TEXT)")
    after_schema = _fingerprint(config_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute("INSERT INTO future_feature(value) VALUES ('novo')")
    after_arbitrary_table = _fingerprint(config_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 8")
    after_user_version = _fingerprint(config_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE sqliteX_user_table(value TEXT)")
        connection.execute("INSERT INTO sqliteX_user_table VALUES ('incluida')")
    after_sqlite_like_user_table = _fingerprint(config_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO arbitrary_domain_table(label) VALUES ('temporario')"
        )
        connection.execute("DELETE FROM arbitrary_domain_table WHERE label = 'temporario'")
    after_sequence_only = _fingerprint(config_path)

    assert len(
        {
            initial,
            after_schema,
            after_arbitrary_table,
            after_user_version,
            after_sqlite_like_user_table,
            after_sequence_only,
        }
    ) == 6


def test_fingerprint_framing_distinguishes_ambiguous_text_boundaries(tmp_path: Path):
    first_database = tmp_path / "first.db"
    second_database = tmp_path / "second.db"
    first_config = tmp_path / "first.json"
    second_config = tmp_path / "second.json"
    for database_path in (first_database, second_database):
        with sqlite3.connect(database_path) as connection:
            connection.execute("CREATE TABLE values_table(left_value TEXT, right_value TEXT)")
    with sqlite3.connect(first_database) as connection:
        connection.execute("INSERT INTO values_table VALUES ('ab', 'c')")
    with sqlite3.connect(second_database) as connection:
        connection.execute("INSERT INTO values_table VALUES ('a', 'bc')")
    _write_config(first_config, first_database)
    _write_config(second_config, second_database)

    assert _fingerprint(first_config) != _fingerprint(second_config)


def test_backup_captures_committed_rows_still_in_wal_and_is_single_file(
    tmp_path: Path,
):
    database_path = tmp_path / "wal-source.db"
    config_path = tmp_path / "app-config.json"
    destination = tmp_path / "backups" / "wal-copy.db"
    with sqlite3.connect(database_path) as setup:
        assert setup.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        setup.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, value TEXT)")
        setup.execute("INSERT INTO events(value) VALUES ('base')")
    _write_config(config_path, database_path)

    reader = sqlite3.connect(database_path)
    try:
        reader.execute("BEGIN")
        assert reader.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        with sqlite3.connect(database_path) as writer:
            writer.execute("INSERT INTO events(value) VALUES ('wal-commit')")
        wal_path = Path(f"{database_path}-wal")
        assert wal_path.is_file() and wal_path.stat().st_size > 0

        result = _run_guard(
            "backup",
            "--config-path",
            config_path,
            "--destination",
            destination,
        )
        payload = _success_payload(result)
    finally:
        reader.close()

    assert payload["journal_mode"] == "delete"
    assert payload["destination"] == str(destination.resolve())
    assert destination.is_file()
    assert not Path(f"{destination}-wal").exists()
    assert not Path(f"{destination}-shm").exists()
    assert _partial_files(destination) == []
    with sqlite3.connect(destination) as backup:
        assert backup.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert backup.execute("SELECT value FROM events ORDER BY id").fetchall() == [
            ("base",),
            ("wal-commit",),
        ]


def test_stale_expected_fingerprint_refuses_backup_without_partial_file(
    tmp_path: Path,
):
    database_path = tmp_path / "stale.db"
    config_path = tmp_path / "app-config.json"
    destination = tmp_path / "backups" / "stale-copy.db"
    _create_database(database_path)
    _write_config(config_path, database_path)
    stale_fingerprint = _fingerprint(config_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO arbitrary_domain_table(label) VALUES ('mudou')"
        )

    result = _run_guard(
        "backup",
        "--config-path",
        config_path,
        "--destination",
        destination,
        "--expected-fingerprint",
        stale_fingerprint,
    )

    payload = _error_payload(result)
    assert payload["error"]["code"] == "stale_fingerprint"
    assert not destination.exists()
    assert not destination.parent.exists()


def test_existing_destination_is_refused_and_preserved(tmp_path: Path):
    database_path = tmp_path / "source.db"
    config_path = tmp_path / "app-config.json"
    destination = tmp_path / "existing.db"
    _create_database(database_path)
    _write_config(config_path, database_path)
    destination.write_bytes(b"nao sobrescrever")
    before_hash = _file_sha256(destination)

    result = _run_guard(
        "backup",
        "--config-path",
        config_path,
        "--destination",
        destination,
    )

    payload = _error_payload(result)
    assert payload["error"]["code"] == "destination_exists"
    assert _file_sha256(destination) == before_hash
    assert _partial_files(destination) == []


@pytest.mark.parametrize(
    ("config_contents", "database_contents", "expected_code"),
    [
        ("{invalid", None, "invalid_config"),
        (None, b"isto nao e sqlite", "invalid_database"),
    ],
)
def test_invalid_config_and_corrupt_database_fail_closed(
    tmp_path: Path,
    config_contents: str | None,
    database_contents: bytes | None,
    expected_code: str,
):
    database_path = tmp_path / "invalid.db"
    config_path = tmp_path / "app-config.json"
    destination = tmp_path / "copy.db"
    if database_contents is not None:
        database_path.write_bytes(database_contents)
        _write_config(config_path, database_path)
    else:
        assert config_contents is not None
        config_path.write_text(config_contents, encoding="utf-8")

    verify = _run_guard("verify", "--config-path", config_path)
    backup = _run_guard(
        "backup",
        "--config-path",
        config_path,
        "--destination",
        destination,
    )

    assert _error_payload(verify)["error"]["code"] == expected_code
    assert _error_payload(backup)["error"]["code"] == expected_code
    assert not destination.exists()
    assert _partial_files(destination) == []


def test_foreign_key_violation_is_invalid_and_not_disclosed(tmp_path: Path):
    database_path = tmp_path / "foreign-key-invalid.db"
    config_path = tmp_path / "app-config.json"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = OFF;
            CREATE TABLE parent(id INTEGER PRIMARY KEY);
            CREATE TABLE child(
                secret_identifier TEXT,
                parent_id INTEGER REFERENCES parent(id)
            );
            INSERT INTO child VALUES ('dado-ultrassecreto', 999);
            """
        )
    _write_config(config_path, database_path)

    result = _run_guard("verify", "--config-path", config_path)
    payload = _error_payload(result)

    assert payload["error"]["code"] == "foreign_key_check_failed"
    assert "dado-ultrassecreto" not in result.stderr


def test_backup_preserves_source_logical_fingerprint_and_validates_destination(
    tmp_path: Path,
):
    database_path = tmp_path / "source.db"
    config_path = tmp_path / "app-config.json"
    backup_config_path = tmp_path / "backup-config.json"
    destination = tmp_path / "backups" / "copy.db"
    _create_database(database_path)
    _write_config(config_path, database_path)
    before = _fingerprint(config_path)

    result = _run_guard(
        "backup",
        "--config-path",
        config_path,
        "--destination",
        destination,
        "--expected-fingerprint",
        before.upper(),
    )
    payload = _success_payload(result)
    after = _fingerprint(config_path)
    _write_config(backup_config_path, destination)
    backup_fingerprint = _fingerprint(backup_config_path)

    assert after == before
    assert backup_fingerprint == before
    assert payload["logical_fingerprint"] == before
    assert payload["backup_sha256"] == _file_sha256(destination)
    assert payload["backup_bytes"] == destination.stat().st_size
    assert payload["quick_check"] == "ok"
    assert payload["quick_check_rows"] == ["ok"]
    assert payload["foreign_key_check"] == []
    assert payload["sha256"] == payload["backup_sha256"]
