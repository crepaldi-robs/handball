from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
LATEST_SCHEMA_VERSION = 1
MIN_SUPPORTED_SCHEMA_VERSION = 1
MAX_SUPPORTED_SCHEMA_VERSION = 1
FINGERPRINT_FORMAT = "crepaldi-handball-logical-sqlite/v1"
FINGERPRINT_DOMAIN = b"crepaldi-handball-logical-sqlite/v1\x00"

DOMAIN_TABLES = {
    "team_members",
    "training_sessions",
    "attendance_records",
    "attendance_audit_log",
    "sync_operations",
}

ColumnContract = tuple[str, str, bool, str | None, int]

EXPECTED_COLUMN_LAYOUTS: dict[str, tuple[ColumnContract, ...]] = {
    "team_members": (
        ("id", "INTEGER", False, None, 1),
        ("name", "TEXT", True, None, 0),
        ("position", "TEXT", True, None, 0),
        ("active", "INTEGER", True, "1", 0),
        ("created_at", "TEXT", True, None, 0),
        ("updated_at", "TEXT", True, None, 0),
    ),
    "training_sessions": (
        ("id", "INTEGER", False, None, 1),
        ("training_date", "TEXT", True, None, 0),
        ("notes", "TEXT", True, "''", 0),
        ("is_finalized", "INTEGER", True, "0", 0),
        ("created_at", "TEXT", True, None, 0),
        ("updated_at", "TEXT", True, None, 0),
    ),
    "attendance_records": (
        ("id", "INTEGER", False, None, 1),
        ("session_id", "INTEGER", True, None, 0),
        ("member_id", "INTEGER", True, None, 0),
        ("confirmation_status", "TEXT", True, "'PENDING'", 0),
        ("present", "INTEGER", False, None, 0),
        ("notes", "TEXT", True, "''", 0),
        ("version", "INTEGER", True, "1", 0),
        ("updated_at", "TEXT", True, None, 0),
    ),
    "attendance_audit_log": (
        ("id", "INTEGER", False, None, 1),
        ("session_id", "INTEGER", True, None, 0),
        ("member_id", "INTEGER", True, None, 0),
        ("old_confirmation_status", "TEXT", False, None, 0),
        ("new_confirmation_status", "TEXT", False, None, 0),
        ("old_present", "INTEGER", False, None, 0),
        ("new_present", "INTEGER", False, None, 0),
        ("old_notes", "TEXT", False, None, 0),
        ("new_notes", "TEXT", False, None, 0),
        ("changed_at", "TEXT", True, None, 0),
        ("source", "TEXT", True, "'ui'", 0),
    ),
    "sync_operations": (
        ("operation_id", "TEXT", False, None, 1),
        ("request_hash", "TEXT", True, None, 0),
        ("response_json", "TEXT", True, None, 0),
        ("created_at", "TEXT", True, None, 0),
    ),
}

REQUIRED_COLUMNS = {
    table: {column[0] for column in layout}
    for table, layout in EXPECTED_COLUMN_LAYOUTS.items()
}

MIGRATION_TABLE_COLUMN_LAYOUT: tuple[ColumnContract, ...] = (
    ("version", "INTEGER", False, None, 1),
    ("name", "TEXT", True, None, 0),
    ("checksum_sha256", "TEXT", True, None, 0),
    ("applied_at", "TEXT", True, None, 0),
    ("app_version", "TEXT", True, None, 0),
    ("origin", "TEXT", True, None, 0),
)

EXPECTED_UNIQUE_CONSTRAINTS = {
    "team_members": frozenset({(("name",), ("NOCASE",))}),
    "training_sessions": frozenset({(("training_date",), ("BINARY",))}),
    "attendance_records": frozenset(
        {(("session_id", "member_id"), ("BINARY", "BINARY"))}
    ),
    "attendance_audit_log": frozenset(),
    "sync_operations": frozenset(),
}

EXPECTED_FOREIGN_KEYS = {
    "team_members": frozenset(),
    "training_sessions": frozenset(),
    "attendance_records": frozenset(
        {
            (
                "session_id",
                "training_sessions",
                "id",
                "NO ACTION",
                "CASCADE",
                "NONE",
            ),
            (
                "member_id",
                "team_members",
                "id",
                "NO ACTION",
                "RESTRICT",
                "NONE",
            ),
        }
    ),
    "attendance_audit_log": frozenset(
        {
            (
                "session_id",
                "training_sessions",
                "id",
                "NO ACTION",
                "CASCADE",
                "NONE",
            ),
            (
                "member_id",
                "team_members",
                "id",
                "NO ACTION",
                "RESTRICT",
                "NONE",
            ),
        }
    ),
    "sync_operations": frozenset(),
}

EXPECTED_NAMED_INDEXES = {
    "idx_attendance_session": ("attendance_records", ("session_id",)),
    "idx_audit_session_changed": (
        "attendance_audit_log",
        ("session_id", "changed_at"),
    ),
    "idx_training_date": ("training_sessions", ("training_date",)),
}

REQUIRED_TABLE_SQL_FRAGMENTS = {
    "team_members": (
        "idintegerprimarykeyautoincrement",
        "check(activein(0,1))",
    ),
    "training_sessions": (
        "idintegerprimarykeyautoincrement",
        "check(is_finalizedin(0,1))",
    ),
    "attendance_records": (
        "idintegerprimarykeyautoincrement",
        "check(presentin(0,1)orpresentisnull)",
    ),
    "attendance_audit_log": ("idintegerprimarykeyautoincrement",),
    "sync_operations": (),
}

SCHEMA_V1_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS team_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL COLLATE NOCASE UNIQUE,
        position TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS training_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        training_date TEXT NOT NULL UNIQUE,
        notes TEXT NOT NULL DEFAULT '',
        is_finalized INTEGER NOT NULL DEFAULT 0
            CHECK (is_finalized IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        confirmation_status TEXT NOT NULL DEFAULT 'PENDING',
        present INTEGER NULL CHECK (present IN (0, 1) OR present IS NULL),
        notes TEXT NOT NULL DEFAULT '',
        version INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL,
        UNIQUE (session_id, member_id),
        FOREIGN KEY (session_id) REFERENCES training_sessions(id)
            ON DELETE CASCADE,
        FOREIGN KEY (member_id) REFERENCES team_members(id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_audit_log (
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
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_operations (
        operation_id TEXT PRIMARY KEY,
        request_hash TEXT NOT NULL,
        response_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_attendance_session
        ON attendance_records(session_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_session_changed
        ON attendance_audit_log(session_id, changed_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_training_date
        ON training_sessions(training_date)
    """,
)

SCHEMA_V1_ADD_VERSION_SQL = (
    "ALTER TABLE attendance_records "
    "ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
)


def _canonical_schema_contract() -> dict[str, Any]:
    """Representação serializável do contrato efetivamente validado na v1."""

    return {
        "domain_tables": sorted(DOMAIN_TABLES),
        "column_layouts": {
            table: [list(column) for column in layout]
            for table, layout in sorted(EXPECTED_COLUMN_LAYOUTS.items())
        },
        "migration_table_column_layout": [
            list(column) for column in MIGRATION_TABLE_COLUMN_LAYOUT
        ],
        "unique_constraints": {
            table: [
                {"columns": list(columns), "collations": list(collations)}
                for columns, collations in sorted(constraints)
            ]
            for table, constraints in sorted(EXPECTED_UNIQUE_CONSTRAINTS.items())
        },
        "foreign_keys": {
            table: [list(foreign_key) for foreign_key in sorted(foreign_keys)]
            for table, foreign_keys in sorted(EXPECTED_FOREIGN_KEYS.items())
        },
        "named_indexes": {
            name: {"table": table, "columns": list(columns)}
            for name, (table, columns) in sorted(EXPECTED_NAMED_INDEXES.items())
        },
        "required_table_sql_fragments": {
            table: list(fragments)
            for table, fragments in sorted(REQUIRED_TABLE_SQL_FRAGMENTS.items())
        },
        "recognized_unversioned_layouts": [
            {
                "name": "ea5404b",
                "missing_tables": ["sync_operations"],
                "missing_columns": {"attendance_records": ["version"]},
                "user_version": 0,
            },
            {
                "name": "pre-ledger-current",
                "missing_tables": [],
                "missing_columns": {},
                "user_version": [0, 1],
            },
            {
                "name": "pre-ledger-without-record-version",
                "missing_tables": [],
                "missing_columns": {"attendance_records": ["version"]},
                "user_version": [0, 1],
            },
        ],
    }


SCHEMA_V1_CONDITIONAL_STEPS = (
    {
        "condition": "attendance_records.version is absent",
        "sql": SCHEMA_V1_ADD_VERSION_SQL,
    },
)


def _migration_checksum(
    version: int,
    name: str,
    statements: Iterable[str],
    *,
    conditional_steps: Iterable[dict[str, str]],
    canonical_contract: dict[str, Any],
) -> str:
    payload = json.dumps(
        {
            "version": version,
            "name": name,
            "statements": [" ".join(statement.split()) for statement in statements],
            "conditional_steps": [
                {
                    "condition": step["condition"],
                    "sql": " ".join(step["sql"].split()),
                }
                for step in conditional_steps
            ],
            "canonical_contract": canonical_contract,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


MIGRATION_V1_NAME = "baseline_schema"
MIGRATION_V1_CHECKSUM = _migration_checksum(
    1,
    MIGRATION_V1_NAME,
    SCHEMA_V1_STATEMENTS,
    conditional_steps=SCHEMA_V1_CONDITIONAL_STEPS,
    canonical_contract=_canonical_schema_contract(),
)
KNOWN_MIGRATIONS = {1: (MIGRATION_V1_NAME, MIGRATION_V1_CHECKSUM)}


class DatabaseSchemaError(RuntimeError):
    """O banco não pode ser usado ou migrado de forma comprovadamente segura."""


@dataclass(frozen=True)
class SchemaStatus:
    database_path: str
    state: str
    current_version: int
    latest_version: int
    minimum_supported_version: int
    maximum_supported_version: int
    compatible: bool
    versioned: bool
    pending_versions: tuple[int, ...]
    problems: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["pending_versions"] = list(self.pending_versions)
        result["problems"] = list(self.problems)
        return result


def _now_iso() -> str:
    return datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _open_read_only(db_path: Path) -> sqlite3.Connection:
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30, cached_statements=0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON").close()
    conn.execute("PRAGMA foreign_keys = ON").close()
    conn.execute("PRAGMA busy_timeout = 30000").close()
    return conn


def _fetchall(conn: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    cursor = conn.execute(sql)
    try:
        return cursor.fetchall()
    finally:
        cursor.close()


def _fetchone(
    conn: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...] = (),
) -> sqlite3.Row | None:
    cursor = conn.execute(sql, parameters)
    try:
        return cursor.fetchone()
    finally:
        cursor.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in _fetchall(
            conn,
            "SELECT name FROM sqlite_schema "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'",
        )
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {item[0] for item in _column_layout(conn, table)}


def _normalize_default(value: object) -> str | None:
    if value is None:
        return None
    return "".join(str(value).split())


def _column_layout(
    conn: sqlite3.Connection,
    table: str,
) -> tuple[ColumnContract, ...]:
    rows = _fetchall(conn, f"PRAGMA table_info({_quote_identifier(table)})")
    return tuple(
        (
            str(row["name"]),
            str(row["type"]).upper(),
            bool(row["notnull"]),
            _normalize_default(row["dflt_value"]),
            int(row["pk"]),
        )
        for row in rows
    )


def _column_layout_problems(
    conn: sqlite3.Connection,
    table: str,
    expected: tuple[ColumnContract, ...],
) -> list[str]:
    actual = _column_layout(conn, table)
    allowed_layouts = {expected}
    if table == "attendance_records" and any(
        item[0] == "version" for item in expected
    ):
        version_column = next(item for item in expected if item[0] == "version")
        allowed_layouts.add(
            tuple(item for item in expected if item[0] != "version")
            + (version_column,)
        )
    if actual in allowed_layouts:
        return []

    expected_names = [item[0] for item in expected]
    actual_names = [item[0] for item in actual]
    missing = [name for name in expected_names if name not in actual_names]
    extra = [name for name in actual_names if name not in expected_names]
    problems: list[str] = []
    if missing:
        problems.append(f"Colunas ausentes em {table}: {', '.join(missing)}.")
    if extra:
        problems.append(f"Colunas inesperadas em {table}: {', '.join(extra)}.")
    if not missing and not extra:
        problems.append(
            f"Definição canônica de colunas divergente em {table} "
            "(ordem, tipo, nulabilidade, default ou chave primária)."
        )
    return problems


def _unique_constraints(
    conn: sqlite3.Connection,
    table: str,
) -> frozenset[tuple[tuple[str, ...], tuple[str, ...]]]:
    constraints: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for index in _fetchall(
        conn,
        f"PRAGMA index_list({_quote_identifier(table)})",
    ):
        if not bool(index["unique"]) or str(index["origin"]) == "pk":
            continue
        details = sorted(
            (
                row
                for row in _fetchall(
                    conn,
                    f"PRAGMA index_xinfo({_quote_identifier(str(index['name']))})",
                )
                if bool(row["key"])
            ),
            key=lambda row: int(row["seqno"]),
        )
        columns = tuple(str(row["name"]) for row in details)
        collations = tuple(str(row["coll"]).upper() for row in details)
        constraints.add((columns, collations))
    return frozenset(constraints)


def _foreign_keys(
    conn: sqlite3.Connection,
    table: str,
) -> frozenset[tuple[str, str, str, str, str, str]]:
    return frozenset(
        (
            str(row["from"]),
            str(row["table"]),
            str(row["to"]),
            str(row["on_update"]).upper(),
            str(row["on_delete"]).upper(),
            str(row["match"]).upper(),
        )
        for row in _fetchall(
            conn,
            f"PRAGMA foreign_key_list({_quote_identifier(table)})",
        )
    )


def _normalized_table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = _fetchone(
        conn,
        "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?",
        (table,),
    )
    if row is None or row["sql"] is None:
        return ""
    return "".join(str(row["sql"]).casefold().split())


def _named_index_problem(
    conn: sqlite3.Connection,
    index_name: str,
    expected_table: str,
    expected_columns: tuple[str, ...],
) -> str | None:
    row = _fetchone(
        conn,
        "SELECT tbl_name FROM sqlite_schema WHERE type = 'index' AND name = ?",
        (index_name,),
    )
    if row is None or str(row["tbl_name"]) != expected_table:
        return f"Índice obrigatório ausente ou associado incorretamente: {index_name}."

    columns = tuple(
        str(item["name"])
        for item in sorted(
            _fetchall(
                conn,
                f"PRAGMA index_info({_quote_identifier(index_name)})",
            ),
            key=lambda item: int(item["seqno"]),
        )
    )
    metadata = next(
        (
            item
            for item in _fetchall(
                conn,
                f"PRAGMA index_list({_quote_identifier(expected_table)})",
            )
            if str(item["name"]) == index_name
        ),
        None,
    )
    if (
        columns != expected_columns
        or metadata is None
        or bool(metadata["unique"])
        or bool(metadata["partial"])
    ):
        return f"Definição divergente do índice obrigatório: {index_name}."
    return None


def _schema_problems(
    conn: sqlite3.Connection,
    *,
    allow_legacy_version_gap: bool = False,
    allowed_missing_tables: frozenset[str] = frozenset(),
) -> list[str]:
    tables = _table_names(conn)
    problems: list[str] = []
    for table, expected_layout in EXPECTED_COLUMN_LAYOUTS.items():
        if table not in tables:
            if table not in allowed_missing_tables:
                problems.append(f"Tabela obrigatória ausente: {table}.")
            continue
        if allow_legacy_version_gap and table == "attendance_records":
            expected_layout = tuple(
                item for item in expected_layout if item[0] != "version"
            )
        problems.extend(
            _column_layout_problems(conn, table, expected_layout)
        )
        actual_unique = _unique_constraints(conn, table)
        expected_unique = EXPECTED_UNIQUE_CONSTRAINTS[table]
        if actual_unique != expected_unique:
            problems.append(
                f"Restrições UNIQUE ou collations divergentes em {table}."
            )
        if _foreign_keys(conn, table) != EXPECTED_FOREIGN_KEYS[table]:
            problems.append(f"Chaves estrangeiras divergentes em {table}.")

        normalized_sql = _normalized_table_sql(conn, table)
        for fragment in REQUIRED_TABLE_SQL_FRAGMENTS[table]:
            if fragment not in normalized_sql:
                problems.append(
                    f"Restrição CHECK/AUTOINCREMENT ausente em {table}: {fragment}."
                )

    for index_name, (table, columns) in EXPECTED_NAMED_INDEXES.items():
        problem = _named_index_problem(conn, index_name, table, columns)
        if problem:
            problems.append(problem)
    return problems


def _status_from_connection(conn: sqlite3.Connection, db_path: Path) -> SchemaStatus:
    tables = _table_names(conn)
    if not tables:
        return SchemaStatus(
            database_path=str(db_path.resolve()),
            state="empty",
            current_version=0,
            latest_version=LATEST_SCHEMA_VERSION,
            minimum_supported_version=MIN_SUPPORTED_SCHEMA_VERSION,
            maximum_supported_version=MAX_SUPPORTED_SCHEMA_VERSION,
            compatible=False,
            versioned=False,
            pending_versions=tuple(range(1, LATEST_SCHEMA_VERSION + 1)),
            problems=(
                "Banco vazio; execute o bootstrap explícito da primeira instalação.",
            ),
        )

    sqlite_user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if "schema_migrations" not in tables:
        if sqlite_user_version not in {0, 1}:
            return SchemaStatus(
                database_path=str(db_path.resolve()),
                state="invalid",
                current_version=sqlite_user_version,
                latest_version=LATEST_SCHEMA_VERSION,
                minimum_supported_version=MIN_SUPPORTED_SCHEMA_VERSION,
                maximum_supported_version=MAX_SUPPORTED_SCHEMA_VERSION,
                compatible=False,
                versioned=False,
                pending_versions=(),
                problems=(
                    "PRAGMA user_version não corresponde a um legado conhecido.",
                ),
            )
        missing_domain_tables = DOMAIN_TABLES - tables
        attendance_columns = (
            _columns(conn, "attendance_records")
            if "attendance_records" in tables
            else set()
        )
        has_version = "version" in attendance_columns
        is_ea5404b_legacy = (
            missing_domain_tables == {"sync_operations"}
            and not has_version
            and sqlite_user_version == 0
        )
        if missing_domain_tables and not is_ea5404b_legacy:
            return SchemaStatus(
                database_path=str(db_path.resolve()),
                state="invalid",
                current_version=0,
                latest_version=LATEST_SCHEMA_VERSION,
                minimum_supported_version=MIN_SUPPORTED_SCHEMA_VERSION,
                maximum_supported_version=MAX_SUPPORTED_SCHEMA_VERSION,
                compatible=False,
                versioned=False,
                pending_versions=tuple(range(1, LATEST_SCHEMA_VERSION + 1)),
                problems=(
                    "Banco parcial; tabelas ausentes: "
                    + ", ".join(sorted(missing_domain_tables))
                    + ".",
                ),
            )

        problems = _schema_problems(
            conn,
            allow_legacy_version_gap=not has_version,
            allowed_missing_tables=(
                frozenset({"sync_operations"})
                if is_ea5404b_legacy
                else frozenset()
            ),
        )
        if problems:
            return SchemaStatus(
                database_path=str(db_path.resolve()),
                state="invalid",
                current_version=0,
                latest_version=LATEST_SCHEMA_VERSION,
                minimum_supported_version=MIN_SUPPORTED_SCHEMA_VERSION,
                maximum_supported_version=MAX_SUPPORTED_SCHEMA_VERSION,
                compatible=False,
                versioned=False,
                pending_versions=(1,),
                problems=tuple(problems),
            )
        if not has_version:
            return SchemaStatus(
                database_path=str(db_path.resolve()),
                state="legacy_requires_migration",
                current_version=0,
                latest_version=LATEST_SCHEMA_VERSION,
                minimum_supported_version=MIN_SUPPORTED_SCHEMA_VERSION,
                maximum_supported_version=MAX_SUPPORTED_SCHEMA_VERSION,
                compatible=False,
                versioned=False,
                pending_versions=(1,),
            )
        return SchemaStatus(
            database_path=str(db_path.resolve()),
            state="legacy_current",
            current_version=1,
            latest_version=LATEST_SCHEMA_VERSION,
            minimum_supported_version=MIN_SUPPORTED_SCHEMA_VERSION,
            maximum_supported_version=MAX_SUPPORTED_SCHEMA_VERSION,
            compatible=True,
            versioned=False,
            pending_versions=(),
        )

    metadata_problems = _column_layout_problems(
        conn,
        "schema_migrations",
        MIGRATION_TABLE_COLUMN_LAYOUT,
    )
    if metadata_problems:
        return SchemaStatus(
            database_path=str(db_path.resolve()),
            state="invalid",
            current_version=0,
            latest_version=LATEST_SCHEMA_VERSION,
            minimum_supported_version=MIN_SUPPORTED_SCHEMA_VERSION,
            maximum_supported_version=MAX_SUPPORTED_SCHEMA_VERSION,
            compatible=False,
            versioned=True,
            pending_versions=tuple(range(1, LATEST_SCHEMA_VERSION + 1)),
            problems=(
                "Tabela schema_migrations possui formato inválido. "
                + " ".join(metadata_problems),
            ),
        )

    rows = conn.execute(
        "SELECT version, name, checksum_sha256 FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied_versions = [int(row["version"]) for row in rows]
    problems: list[str] = []
    if not rows:
        problems.append(
            "Histórico schema_migrations vazio não corresponde a um estado conhecido."
        )
    expected_sequence = list(range(1, max(applied_versions, default=0) + 1))
    if applied_versions != expected_sequence:
        problems.append("Histórico de migrações não é contínuo a partir da versão 1.")
    for row in rows:
        version = int(row["version"])
        known = KNOWN_MIGRATIONS.get(version)
        if known is None:
            problems.append(f"Migração desconhecida registrada: versão {version}.")
            continue
        expected_name, expected_checksum = known
        if (
            row["name"] != expected_name
            or row["checksum_sha256"] != expected_checksum
        ):
            problems.append(f"Checksum divergente na migração {version}.")

    current_version = max(applied_versions, default=0)
    if sqlite_user_version != current_version:
        problems.append(
            "PRAGMA user_version diverge do histórico schema_migrations."
        )
    if current_version >= 1:
        problems.extend(_schema_problems(conn))
    compatible = (
        not problems
        and MIN_SUPPORTED_SCHEMA_VERSION
        <= current_version
        <= MAX_SUPPORTED_SCHEMA_VERSION
    )
    pending = tuple(
        version
        for version in range(current_version + 1, LATEST_SCHEMA_VERSION + 1)
    )
    if problems:
        state = "invalid"
    elif compatible and not pending:
        state = "current"
    else:
        state = "migration_required"
    return SchemaStatus(
        database_path=str(db_path.resolve()),
        state=state,
        current_version=current_version,
        latest_version=LATEST_SCHEMA_VERSION,
        minimum_supported_version=MIN_SUPPORTED_SCHEMA_VERSION,
        maximum_supported_version=MAX_SUPPORTED_SCHEMA_VERSION,
        compatible=compatible,
        versioned=True,
        pending_versions=pending,
        problems=tuple(problems),
    )


def _create_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            app_version TEXT NOT NULL,
            origin TEXT NOT NULL
        )
        """
    )


def _apply_schema_v1(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_V1_STATEMENTS:
        conn.execute(statement)
    if "version" not in _columns(conn, "attendance_records"):
        conn.execute(SCHEMA_V1_ADD_VERSION_SQL)


def migration_manifest(status: SchemaStatus) -> list[dict[str, object]]:
    """Lista ordenada e imutável que vincula o plano ao código de migração."""

    manifest: list[dict[str, object]] = []
    for version, (name, checksum) in sorted(KNOWN_MIGRATIONS.items()):
        if status.problems:
            action = (
                "bootstrap-required"
                if status.state in {"missing", "empty"}
                else "blocked"
            )
        elif status.versioned and version <= status.current_version:
            action = "already-applied"
        elif status.state == "legacy_current" and version == 1:
            action = "adopt-baseline"
        elif version in status.pending_versions or not status.versioned:
            action = "apply"
        else:
            action = "not-applicable"
        manifest.append(
            {
                "version": version,
                "name": name,
                "checksum_sha256": checksum,
                "action": action,
            }
        )
    return manifest


def _record_schema_v1(
    conn: sqlite3.Connection,
    *,
    app_version: str,
    origin: str,
) -> None:
    _create_migration_table(conn)
    conn.execute(
        """
        INSERT INTO schema_migrations(
            version, name, checksum_sha256, applied_at,
            app_version, origin
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(version) DO NOTHING
        """,
        (
            1,
            MIGRATION_V1_NAME,
            MIGRATION_V1_CHECKSUM,
            _now_iso(),
            app_version,
            origin,
        ),
    )
    conn.execute("PRAGMA user_version = 1").close()


def _verify_transaction_integrity(conn: sqlite3.Connection) -> None:
    quick_check_rows = [str(row[0]) for row in _fetchall(conn, "PRAGMA quick_check")]
    if quick_check_rows != ["ok"]:
        detail = "; ".join(quick_check_rows) or "sem resultado"
        raise DatabaseSchemaError(
            f"PRAGMA quick_check reprovou o banco dentro da transação: {detail}"
        )
    if _fetchall(conn, "PRAGMA foreign_key_check"):
        raise DatabaseSchemaError(
            "PRAGMA foreign_key_check encontrou violações dentro da transação."
        )


def _remove_new_database_files(db_path: Path) -> None:
    """Remove somente artefatos de um candidato de bootstrap que nunca existiu."""

    for candidate in (
        db_path,
        Path(str(db_path) + "-journal"),
        Path(str(db_path) + "-wal"),
        Path(str(db_path) + "-shm"),
    ):
        candidate.unlink(missing_ok=True)


class DatabaseMigrator:
    """Planeja e aplica somente migrações explícitas do SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def status(self) -> SchemaStatus:
        if not self.db_path.exists():
            return SchemaStatus(
                database_path=str(self.db_path.resolve()),
                state="missing",
                current_version=0,
                latest_version=LATEST_SCHEMA_VERSION,
                minimum_supported_version=MIN_SUPPORTED_SCHEMA_VERSION,
                maximum_supported_version=MAX_SUPPORTED_SCHEMA_VERSION,
                compatible=False,
                versioned=False,
                pending_versions=tuple(range(1, LATEST_SCHEMA_VERSION + 1)),
                problems=(
                    "Banco ausente; execute o bootstrap explícito da primeira instalação.",
                ),
            )
        conn = _open_read_only(self.db_path)
        try:
            return _status_from_connection(conn, self.db_path)
        finally:
            conn.close()

    def apply_pending(
        self,
        *,
        app_version: str = "unknown",
        origin: str = "database-migrate",
        expected_fingerprint: str | None = None,
    ) -> SchemaStatus:
        if not self.db_path.is_file():
            raise DatabaseSchemaError(
                "Migração recusada: o banco existente não foi encontrado; "
                "use o bootstrap explícito da primeira instalação."
            )
        if not expected_fingerprint:
            raise DatabaseSchemaError(
                "Migração recusada: expected_fingerprint é obrigatório."
            )

        database_uri = f"{self.db_path.resolve().as_uri()}?mode=rw"
        conn = sqlite3.connect(
            database_uri,
            uri=True,
            timeout=30,
            isolation_level=None,
            cached_statements=0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON").close()
        conn.execute("PRAGMA busy_timeout = 30000").close()
        try:
            conn.execute("BEGIN IMMEDIATE").close()
            actual_fingerprint = fingerprint_from_connection(conn)
            if actual_fingerprint != expected_fingerprint:
                raise DatabaseSchemaError(
                    "O banco mudou depois do plano; migração recusada."
                )
            before = _status_from_connection(conn, self.db_path)
            if before.problems:
                raise DatabaseSchemaError(" ".join(before.problems))
            if before.versioned and before.current_version > LATEST_SCHEMA_VERSION:
                raise DatabaseSchemaError(
                    "O banco é mais novo que este aplicativo; migração recusada."
                )

            needs_v1 = before.current_version < 1 or not before.versioned
            if needs_v1:
                _apply_schema_v1(conn)
                _record_schema_v1(
                    conn,
                    app_version=app_version,
                    origin=origin,
                )

            after = _status_from_connection(conn, self.db_path)
            if not after.compatible or not after.versioned or after.problems:
                raise DatabaseSchemaError(
                    "A migração não produziu um esquema versionado compatível. "
                    + " ".join(after.problems)
                )
            _verify_transaction_integrity(conn)
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()
        return after

    def bootstrap_new(
        self,
        *,
        app_version: str = "unknown",
        origin: str = "initial-bootstrap",
    ) -> SchemaStatus:
        """Cria um candidato novo; nunca abre, reaproveita ou altera um existente."""

        if self.db_path.exists():
            raise FileExistsError(
                f"O candidato de bootstrap já existe: {self.db_path}"
            )
        if not self.db_path.parent.is_dir():
            raise FileNotFoundError(
                f"Diretório do bootstrap não existe: {self.db_path.parent}"
            )

        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(
                self.db_path,
                timeout=30,
                isolation_level=None,
                cached_statements=0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON").close()
            conn.execute("PRAGMA busy_timeout = 30000").close()
            journal_mode_row = conn.execute("PRAGMA journal_mode = WAL").fetchone()
            journal_mode = (
                str(journal_mode_row[0]).casefold() if journal_mode_row else ""
            )
            if journal_mode != "wal":
                raise DatabaseSchemaError(
                    "O bootstrap não conseguiu ativar o journal_mode WAL."
                )
            conn.execute("BEGIN IMMEDIATE").close()
            _apply_schema_v1(conn)
            _record_schema_v1(
                conn,
                app_version=app_version,
                origin=origin,
            )
            result = _status_from_connection(conn, self.db_path)
            if not result.compatible or not result.versioned or result.problems:
                raise DatabaseSchemaError(
                    "O bootstrap não produziu um esquema versionado compatível. "
                    + " ".join(result.problems)
                )
            _verify_transaction_integrity(conn)
            conn.commit()
            conn.close()
            conn = None

            verified = self.status()
            if not verified.compatible or not verified.versioned:
                raise DatabaseSchemaError(
                    "O candidato de bootstrap falhou na verificação após o commit."
                )
            return verified
        except Exception:
            if conn is not None and conn.in_transaction:
                conn.rollback()
            if conn is not None:
                conn.close()
                conn = None
            _remove_new_database_files(self.db_path)
            raise
        finally:
            if conn is not None:
                conn.close()


def _canonical_sqlite_value(value: object) -> list[str]:
    if value is None:
        return ["null", ""]
    if isinstance(value, int):
        return ["integer", str(value)]
    if isinstance(value, float):
        return ["real", value.hex()]
    if isinstance(value, str):
        return ["text", value]
    if isinstance(value, bytes):
        return ["blob", value.hex()]
    raise DatabaseSchemaError(
        "O banco contém um tipo de valor SQLite não suportado pelo fingerprint."
    )


def _canonical_row(row: Iterable[object]) -> bytes:
    return json.dumps(
        [_canonical_sqlite_value(value) for value in row],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")


def _add_fingerprint_frame(digest: Any, label: str, payload: bytes) -> None:
    label_bytes = label.encode("utf-8")
    digest.update(len(label_bytes).to_bytes(8, "big"))
    digest.update(label_bytes)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def fingerprint_from_connection(conn: sqlite3.Connection) -> str:
    """Calcula o hash lógico na conexão e no snapshot/transação já adquiridos."""

    digest = hashlib.sha256()
    digest.update(FINGERPRINT_DOMAIN)
    user_version_row = _fetchone(conn, "PRAGMA user_version")
    user_version = int(user_version_row[0]) if user_version_row else 0
    _add_fingerprint_frame(
        digest,
        "user_version",
        str(user_version).encode("ascii"),
    )
    schema_rows = sorted(
        _canonical_row(tuple(row))
        for row in _fetchall(
            conn,
            "SELECT type, name, tbl_name, sql FROM sqlite_schema",
        )
    )
    _add_fingerprint_frame(
        digest,
        "sqlite_schema.count",
        str(len(schema_rows)).encode("ascii"),
    )
    for schema_row in schema_rows:
        _add_fingerprint_frame(digest, "sqlite_schema.row", schema_row)

    table_names = {
        str(row[0])
        for row in _fetchall(
            conn,
            "SELECT name FROM sqlite_schema "
            "WHERE type = 'table' "
            "AND lower(substr(name, 1, 7)) <> 'sqlite_'",
        )
    }
    sequence_exists = _fetchone(
        conn,
        "SELECT 1 FROM sqlite_schema "
        "WHERE type = 'table' AND name = 'sqlite_sequence'",
    )
    if sequence_exists:
        table_names.add("sqlite_sequence")

    # Não há allowlist aqui: toda tabela criada pelo usuário participa da prova
    # de não mutação, inclusive extensões futuras ainda desconhecidas pela app.
    _add_fingerprint_frame(
        digest,
        "tables.count",
        str(len(table_names)).encode("ascii"),
    )
    for table in sorted(table_names):
        column_rows = _fetchall(
            conn,
            f"PRAGMA table_xinfo({_quote_identifier(table)})",
        )
        columns = [str(row[1]) for row in column_rows]
        if not columns:
            raise DatabaseSchemaError(
                "Uma tabela do banco não possui uma definição legível."
            )
        table_payload = json.dumps(
            {"columns": columns, "name": table},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        _add_fingerprint_frame(digest, "table", table_payload)

        quoted_columns = ",".join(_quote_identifier(column) for column in columns)
        rows = _fetchall(
            conn,
            f"SELECT {quoted_columns} FROM {_quote_identifier(table)}",
        )
        canonical_rows = sorted(_canonical_row(tuple(row)) for row in rows)
        _add_fingerprint_frame(
            digest,
            "table.rows.count",
            str(len(canonical_rows)).encode("ascii"),
        )
        for canonical_row in canonical_rows:
            _add_fingerprint_frame(digest, "table.row", canonical_row)
    return digest.hexdigest()


def logical_fingerprint(db_path: str | Path) -> str:
    """Hash determinístico de esquema e conteúdo, sem alterar o SQLite."""

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(path)
    conn = _open_read_only(path)
    try:
        return fingerprint_from_connection(conn)
    finally:
        conn.close()


def verify_database(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {
            "database_path": str(path.resolve()),
            "quick_check": "missing",
            "ok": False,
            "logical_fingerprint": None,
        }
    conn = _open_read_only(path)
    try:
        quick_check_rows = [str(row[0]) for row in conn.execute("PRAGMA quick_check")]
        foreign_key_rows = [
            tuple(row) for row in conn.execute("PRAGMA foreign_key_check")
        ]
    finally:
        conn.close()
    quick_check = "ok" if quick_check_rows == ["ok"] else "\n".join(quick_check_rows)
    return {
        "database_path": str(path.resolve()),
        "quick_check": quick_check,
        "foreign_key_check": foreign_key_rows,
        "ok": quick_check == "ok" and not foreign_key_rows,
        "logical_fingerprint": logical_fingerprint(path),
    }
