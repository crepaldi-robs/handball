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
LATEST_SCHEMA_VERSION = 11
MIN_SUPPORTED_SCHEMA_VERSION = 1
MAX_SUPPORTED_SCHEMA_VERSION = 11
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

SCHEMA_V2_STATEMENTS = (
    "CREATE TABLE people (id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL, display_name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, person_id INTEGER UNIQUE, username TEXT NOT NULL COLLATE NOCASE UNIQUE, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)), must_change_password INTEGER NOT NULL DEFAULT 0 CHECK(must_change_password IN(0,1)), credential_version INTEGER NOT NULL DEFAULT 1, last_login_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE RESTRICT)",
    "CREATE TABLE teams (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, slug TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE seasons (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL, label TEXT NOT NULL, starts_on TEXT, ends_on TEXT, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)), UNIQUE(team_id,label), FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE RESTRICT)",
    "CREATE TABLE team_memberships (id INTEGER PRIMARY KEY AUTOINCREMENT, person_id INTEGER NOT NULL, team_id INTEGER NOT NULL, season_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE', valid_from TEXT, valid_to TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(person_id,team_id,season_id), FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE RESTRICT, FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE RESTRICT, FOREIGN KEY(season_id) REFERENCES seasons(id) ON DELETE RESTRICT)",
    "CREATE TABLE membership_roles (membership_id INTEGER NOT NULL, role_code TEXT NOT NULL CHECK(role_code IN('CT','PLAYER')), PRIMARY KEY(membership_id,role_code), FOREIGN KEY(membership_id) REFERENCES team_memberships(id) ON DELETE CASCADE)",
    "CREATE TABLE system_roles (user_id INTEGER NOT NULL, role_code TEXT NOT NULL CHECK(role_code IN('DEV','CT','PLAYER')), PRIMARY KEY(user_id,role_code), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)",
    "CREATE TABLE player_user_links (team_member_id INTEGER NOT NULL UNIQUE, person_id INTEGER NOT NULL UNIQUE, user_id INTEGER UNIQUE, PRIMARY KEY(team_member_id), FOREIGN KEY(team_member_id) REFERENCES team_members(id) ON DELETE RESTRICT, FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE RESTRICT, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE auth_sessions (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, token_hash TEXT NOT NULL UNIQUE, csrf_token TEXT NOT NULL, credential_version INTEGER NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT, last_seen_at TEXT, user_agent_hash TEXT, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)",
    "ALTER TABLE attendance_audit_log ADD COLUMN actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE attendance_audit_log ADD COLUMN action TEXT",
    "ALTER TABLE attendance_audit_log ADD COLUMN target_id TEXT",
    "ALTER TABLE attendance_audit_log ADD COLUMN operation_id TEXT",
    "CREATE TABLE security_audit_events (id INTEGER PRIMARY KEY AUTOINCREMENT, actor_user_id INTEGER, occurred_at TEXT NOT NULL, action TEXT NOT NULL, entity TEXT NOT NULL, target_id TEXT, origin TEXT NOT NULL, before_json TEXT, after_json TEXT, request_id TEXT, FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL)",
    "CREATE INDEX idx_auth_sessions_user ON auth_sessions(user_id, revoked_at)",
    "CREATE INDEX idx_security_audit_occurred ON security_audit_events(occurred_at)",
)
MIGRATION_V2_NAME = "hm_ime_users_authorization"
MIGRATION_V2_CHECKSUM = _migration_checksum(2, MIGRATION_V2_NAME, SCHEMA_V2_STATEMENTS, conditional_steps=(), canonical_contract={"organization":"HM_IME","season":"2026.2","roles":["DEV","CT","PLAYER"]})
KNOWN_MIGRATIONS[2] = (MIGRATION_V2_NAME, MIGRATION_V2_CHECKSUM)

V2_REQUIRED_COLUMNS = {
    "people": {"id", "full_name", "display_name", "active", "created_at", "updated_at"},
    "users": {"id", "person_id", "username", "password_hash", "active", "must_change_password", "credential_version", "last_login_at", "created_at", "updated_at"},
    "teams": {"id", "code", "slug", "display_name", "active", "created_at", "updated_at"},
    "seasons": {"id", "team_id", "label", "starts_on", "ends_on", "active"},
    "team_memberships": {"id", "person_id", "team_id", "season_id", "status", "valid_from", "valid_to", "created_at", "updated_at"},
    "membership_roles": {"membership_id", "role_code"},
    "system_roles": {"user_id", "role_code"},
    "player_user_links": {"team_member_id", "person_id", "user_id"},
    "auth_sessions": {"id", "user_id", "token_hash", "csrf_token", "credential_version", "created_at", "expires_at", "revoked_at", "last_seen_at", "user_agent_hash"},
    "security_audit_events": {"id", "actor_user_id", "occurred_at", "action", "entity", "target_id", "origin", "before_json", "after_json", "request_id"},
}

SCHEMA_V3_STATEMENTS = (
    "CREATE UNIQUE INDEX idx_seasons_id_team ON seasons(id,team_id)",
    "CREATE TABLE calendar_events (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL, season_id INTEGER NOT NULL, event_type TEXT NOT NULL CHECK(event_type IN('TRAINING','GAME','CHAMPIONSHIP','MILESTONE_HOLIDAY','COLLECTIVE_RESTRICTION','CANCELLATION_RESCHEDULING')), status TEXT NOT NULL CHECK(status IN('PLANNED','CONFIRMED','CANCELLED','RESCHEDULED','COMPLETED')), starts_at TEXT NOT NULL, ends_at TEXT NOT NULL CHECK(ends_at>starts_at), location TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', restriction_kind TEXT CHECK(restriction_kind IN('CHAMPIONSHIP_DATES','COURT_UNAVAILABLE','RAIN','HOLIDAY') OR restriction_kind IS NULL), attendance_session_id INTEGER, created_by_user_id INTEGER NOT NULL, updated_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, CHECK((event_type='COLLECTIVE_RESTRICTION' AND restriction_kind IS NOT NULL) OR (event_type<>'COLLECTIVE_RESTRICTION' AND restriction_kind IS NULL)), CHECK(attendance_session_id IS NULL OR event_type='TRAINING'), CHECK(event_type<>'CANCELLATION_RESCHEDULING' OR status IN('CANCELLED','RESCHEDULED')), FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE RESTRICT, FOREIGN KEY(season_id,team_id) REFERENCES seasons(id,team_id) ON DELETE RESTRICT, FOREIGN KEY(attendance_session_id) REFERENCES training_sessions(id) ON DELETE SET NULL, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(updated_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE calendar_justifications (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, player_member_id INTEGER NOT NULL, reason TEXT NOT NULL CHECK(length(trim(reason))>0), created_by_user_id INTEGER NOT NULL, updated_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(event_id,player_member_id), FOREIGN KEY(event_id) REFERENCES calendar_events(id) ON DELETE CASCADE, FOREIGN KEY(player_member_id) REFERENCES team_members(id) ON DELETE RESTRICT, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(updated_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE INDEX idx_calendar_events_team_season_start ON calendar_events(team_id,season_id,starts_at)",
    "CREATE INDEX idx_calendar_events_interval ON calendar_events(starts_at,ends_at)",
    "CREATE INDEX idx_calendar_justifications_player ON calendar_justifications(player_member_id,event_id)",
)
MIGRATION_V3_NAME = "calendar_events_justifications"
MIGRATION_V3_CHECKSUM = _migration_checksum(
    3,
    MIGRATION_V3_NAME,
    SCHEMA_V3_STATEMENTS,
    conditional_steps=(),
    canonical_contract={
        "season": "2026.2",
        "season_dates": None,
        "attendance_link": "optional-reference-only",
        "justification_workflow": "self-service-no-approval-no-effect",
    },
)
KNOWN_MIGRATIONS[3] = (MIGRATION_V3_NAME, MIGRATION_V3_CHECKSUM)

MIGRATION_V4_NAME = "calendar_attendance_source_of_truth"
MIGRATION_V4_CHECKSUM = _migration_checksum(
    4,
    MIGRATION_V4_NAME,
    (),
    conditional_steps=(
        {
            "condition": "training_sessions.training_date has a unique constraint",
            "sql": "rebuild training_sessions without unique(training_date)",
        },
        {
            "condition": "calendar_events.attendance_session_id is not unique",
            "sql": "create partial unique index on calendar_events(attendance_session_id)",
        },
    ),
    canonical_contract={
        "calendar_event_attendance_link": "canonical",
        "attendance_session_multiple_same_day": True,
        "timezone": "America/Sao_Paulo",
    },
)
KNOWN_MIGRATIONS[4] = (MIGRATION_V4_NAME, MIGRATION_V4_CHECKSUM)

SCHEMA_V5_STATEMENTS = (
    "CREATE TABLE user_permission_grants (user_id INTEGER NOT NULL, permission_code TEXT NOT NULL CHECK(permission_code IN('sql.explore','sql.admin')), granted_by_user_id INTEGER NOT NULL, granted_at TEXT NOT NULL, PRIMARY KEY(user_id,permission_code), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY(granted_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE INDEX idx_user_permission_grants_actor ON user_permission_grants(granted_by_user_id,granted_at)",
)
MIGRATION_V5_NAME = "individual_sql_permission_grants"
MIGRATION_V5_CHECKSUM = _migration_checksum(
    5,
    MIGRATION_V5_NAME,
    SCHEMA_V5_STATEMENTS,
    conditional_steps=(),
    canonical_contract={
        "permissions": ["sql.explore", "sql.admin"],
        "effective_permissions": "role-union-direct-grants",
        "audit": "security_audit_events",
        "column_layout": [
            ["user_id", "INTEGER", True, None, 1],
            ["permission_code", "TEXT", True, None, 2],
            ["granted_by_user_id", "INTEGER", True, None, 0],
            ["granted_at", "TEXT", True, None, 0],
        ],
        "foreign_keys": [
            ["user_id", "users", "id", "NO ACTION", "CASCADE", "NONE"],
            ["granted_by_user_id", "users", "id", "NO ACTION", "RESTRICT", "NONE"],
        ],
        "check": "permission_code in ('sql.explore','sql.admin')",
        "named_index": {
            "name": "idx_user_permission_grants_actor",
            "columns": ["granted_by_user_id", "granted_at"],
            "unique": False,
            "partial": False,
        },
    },
)
KNOWN_MIGRATIONS[5] = (MIGRATION_V5_NAME, MIGRATION_V5_CHECKSUM)

SCHEMA_V6_STATEMENTS = (
    "CREATE TABLE attendance_record_positions (attendance_record_id INTEGER NOT NULL, position TEXT NOT NULL CHECK(length(trim(position))>0), ordinal INTEGER NOT NULL CHECK(ordinal>=0), PRIMARY KEY(attendance_record_id,position), UNIQUE(attendance_record_id,ordinal), FOREIGN KEY(attendance_record_id) REFERENCES attendance_records(id) ON DELETE CASCADE)",
    "CREATE INDEX idx_attendance_record_positions_record ON attendance_record_positions(attendance_record_id,ordinal)",
)
MIGRATION_V6_NAME = "player_self_confirmation_positions"
MIGRATION_V6_CHECKSUM = _migration_checksum(
    6,
    MIGRATION_V6_NAME,
    SCHEMA_V6_STATEMENTS,
    conditional_steps=(),
    canonical_contract={"player_self_confirmation": "server-scoped", "positions": "many-per-attendance-record"},
)
KNOWN_MIGRATIONS[6] = (MIGRATION_V6_NAME, MIGRATION_V6_CHECKSUM)

SCHEMA_V7_STATEMENTS = (
    "CREATE TABLE calendar_event_series (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL, season_id INTEGER NOT NULL, event_type TEXT NOT NULL CHECK(event_type IN('TRAINING','GAME','CHAMPIONSHIP','MILESTONE_HOLIDAY','COLLECTIVE_RESTRICTION','CANCELLATION_RESCHEDULING')), title TEXT NOT NULL DEFAULT '', opponent TEXT NOT NULL DEFAULT '', starts_on TEXT NOT NULL, ends_on TEXT NOT NULL, start_time TEXT NOT NULL, duration_minutes INTEGER NOT NULL CHECK(duration_minutes>0), weekdays_json TEXT NOT NULL, location TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', restriction_kind TEXT CHECK(restriction_kind IN('CHAMPIONSHIP_DATES','COURT_UNAVAILABLE','RAIN','HOLIDAY') OR restriction_kind IS NULL), created_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE RESTRICT, FOREIGN KEY(season_id,team_id) REFERENCES seasons(id,team_id) ON DELETE RESTRICT, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "ALTER TABLE calendar_events ADD COLUMN title TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calendar_events ADD COLUMN opponent TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE calendar_events ADD COLUMN all_day INTEGER NOT NULL DEFAULT 0 CHECK(all_day IN(0,1))",
    "ALTER TABLE calendar_events ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1)",
    "ALTER TABLE calendar_events ADD COLUMN series_id INTEGER REFERENCES calendar_event_series(id) ON DELETE SET NULL",
    "CREATE TABLE calendar_event_transitions (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, action TEXT NOT NULL CHECK(action IN('CREATE','UPDATE','CONFIRM','COMPLETE','CANCEL','UNDO_CANCEL','RESCHEDULE','SERIES_CREATE')), from_status TEXT, to_status TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', replacement_event_id INTEGER, actor_user_id INTEGER NOT NULL, occurred_at TEXT NOT NULL, before_json TEXT, after_json TEXT, FOREIGN KEY(event_id) REFERENCES calendar_events(id) ON DELETE CASCADE, FOREIGN KEY(replacement_event_id) REFERENCES calendar_events(id) ON DELETE SET NULL, FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE calendar_command_receipts (operation_id TEXT PRIMARY KEY, actor_user_id INTEGER NOT NULL, request_hash TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE INDEX idx_calendar_series_team_season ON calendar_event_series(team_id,season_id,starts_on)",
    "CREATE INDEX idx_calendar_events_series ON calendar_events(series_id,starts_at)",
    "CREATE INDEX idx_calendar_transitions_event ON calendar_event_transitions(event_id,occurred_at,id)",
    "CREATE INDEX idx_calendar_receipts_created ON calendar_command_receipts(created_at)",
)
MIGRATION_V7_NAME = "calendar_professional_workflow"
MIGRATION_V7_CHECKSUM = _migration_checksum(
    7,
    MIGRATION_V7_NAME,
    SCHEMA_V7_STATEMENTS,
    conditional_steps=(),
    canonical_contract={
        "event_lifecycle": "explicit-reversible-transitions",
        "hard_delete": False,
        "idempotency": "operation-receipts",
        "recurrence": "transactional-series",
        "optimistic_concurrency": "event-version",
    },
)
KNOWN_MIGRATIONS[7] = (MIGRATION_V7_NAME, MIGRATION_V7_CHECKSUM)

# O Playbook não fixa a taxonomia esportiva no esquema. Pastas, conteúdos e
# vínculos são dados do time, sempre identificados por IDs permanentes.
SCHEMA_V8_STATEMENTS = (
    "CREATE TABLE playbook_folders (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL, parent_id INTEGER, name TEXT NOT NULL CHECK(length(trim(name))>0), sort_order INTEGER NOT NULL DEFAULT 0, archived_at TEXT, archived_by_user_id INTEGER, created_by_user_id INTEGER NOT NULL, updated_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE RESTRICT, FOREIGN KEY(parent_id) REFERENCES playbook_folders(id) ON DELETE RESTRICT, FOREIGN KEY(archived_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(updated_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_contents (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL, title TEXT NOT NULL CHECK(length(trim(title))>0), content_kind TEXT NOT NULL DEFAULT 'CONTENT', status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN('DRAFT','PUBLISHED','ARCHIVED')), perspective TEXT CHECK(perspective IN('ATTACK','DEFENSE','NEUTRAL') OR perspective IS NULL), objective TEXT NOT NULL DEFAULT '', when_to_use TEXT NOT NULL DEFAULT '', prerequisites TEXT NOT NULL DEFAULT '', steps TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', current_revision INTEGER NOT NULL DEFAULT 1 CHECK(current_revision>=1), published_at TEXT, published_by_user_id INTEGER, archived_at TEXT, archived_by_user_id INTEGER, created_by_user_id INTEGER NOT NULL, updated_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE RESTRICT, FOREIGN KEY(published_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(archived_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(updated_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_content_revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER NOT NULL, revision_number INTEGER NOT NULL CHECK(revision_number>=1), snapshot_json TEXT NOT NULL, change_note TEXT NOT NULL DEFAULT '', restored_from_revision_id INTEGER, created_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(content_id,revision_number), FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE CASCADE, FOREIGN KEY(restored_from_revision_id) REFERENCES playbook_content_revisions(id) ON DELETE SET NULL, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_content_folders (content_id INTEGER NOT NULL, folder_id INTEGER NOT NULL, placement_kind TEXT NOT NULL DEFAULT 'PLACEMENT' CHECK(placement_kind IN('PLACEMENT','SHORTCUT')), sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, PRIMARY KEY(content_id,folder_id), FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE CASCADE, FOREIGN KEY(folder_id) REFERENCES playbook_folders(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_content_aliases (content_id INTEGER NOT NULL, alias TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(alias))>0), PRIMARY KEY(content_id,alias), FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE CASCADE)",
    "CREATE TABLE playbook_content_positions (content_id INTEGER NOT NULL, position TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(position))>0), PRIMARY KEY(content_id,position), FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE CASCADE)",
    "CREATE TABLE playbook_content_relations (id INTEGER PRIMARY KEY AUTOINCREMENT, source_content_id INTEGER NOT NULL, target_content_id INTEGER NOT NULL, relation_type TEXT NOT NULL CHECK(relation_type IN('PROPOSAL','RESPONSE','COUNTERRESPONSE','VARIATION')), created_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, CHECK(source_content_id<>target_content_id), UNIQUE(source_content_id,target_content_id,relation_type), FOREIGN KEY(source_content_id) REFERENCES playbook_contents(id) ON DELETE CASCADE, FOREIGN KEY(target_content_id) REFERENCES playbook_contents(id) ON DELETE CASCADE, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_attachments (id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER NOT NULL, storage_kind TEXT NOT NULL CHECK(storage_kind IN('DRIVE_LINK','LOCAL_FILE')), label TEXT NOT NULL DEFAULT '', url TEXT, storage_key TEXT, mime_type TEXT NOT NULL DEFAULT '', size_bytes INTEGER, offline_essential INTEGER NOT NULL DEFAULT 0 CHECK(offline_essential IN(0,1)), created_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, CHECK((storage_kind='DRIVE_LINK' AND url IS NOT NULL AND storage_key IS NULL) OR (storage_kind='LOCAL_FILE' AND url IS NULL AND storage_key IS NOT NULL)), FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE CASCADE, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_favorites (user_id INTEGER NOT NULL, content_id INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id,content_id), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE CASCADE)",
    "CREATE TABLE playbook_recent_views (user_id INTEGER NOT NULL, content_id INTEGER NOT NULL, last_viewed_at TEXT NOT NULL, view_count INTEGER NOT NULL DEFAULT 1 CHECK(view_count>=1), PRIMARY KEY(user_id,content_id), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE CASCADE)",
    "CREATE TABLE playbook_training_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, calendar_event_id INTEGER NOT NULL UNIQUE, team_id INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '', seasonal_objective TEXT NOT NULL DEFAULT '', context_adjustment TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', created_by_user_id INTEGER NOT NULL, updated_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(calendar_event_id) REFERENCES calendar_events(id) ON DELETE RESTRICT, FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE RESTRICT, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(updated_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_training_plan_items (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER NOT NULL, content_id INTEGER NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, planned_minutes INTEGER CHECK(planned_minutes IS NULL OR planned_minutes>0), notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE(plan_id,content_id), FOREIGN KEY(plan_id) REFERENCES playbook_training_plans(id) ON DELETE CASCADE, FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_plan_transfers (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER NOT NULL, from_event_id INTEGER NOT NULL, to_event_id INTEGER NOT NULL, reason TEXT NOT NULL DEFAULT '', actor_user_id INTEGER NOT NULL, transferred_at TEXT NOT NULL, FOREIGN KEY(plan_id) REFERENCES playbook_training_plans(id) ON DELETE RESTRICT, FOREIGN KEY(from_event_id) REFERENCES calendar_events(id) ON DELETE RESTRICT, FOREIGN KEY(to_event_id) REFERENCES calendar_events(id) ON DELETE RESTRICT, FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_plan_evaluations (id INTEGER PRIMARY KEY AUTOINCREMENT, calendar_event_id INTEGER NOT NULL, content_id INTEGER NOT NULL, mastery_stage TEXT NOT NULL CHECK(mastery_stage IN('STARTING','IMPROVING','REFINING','CONSOLIDATED')), continuity_decision TEXT NOT NULL CHECK(continuity_decision IN('CONTINUE','COMPLETE','REVIEW')), notes TEXT NOT NULL DEFAULT '', actor_user_id INTEGER NOT NULL, evaluated_at TEXT NOT NULL, UNIQUE(calendar_event_id,content_id), FOREIGN KEY(calendar_event_id) REFERENCES calendar_events(id) ON DELETE RESTRICT, FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE RESTRICT, FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE INDEX idx_playbook_folders_team_parent_order ON playbook_folders(team_id,parent_id,sort_order,id)",
    "CREATE INDEX idx_playbook_contents_team_status ON playbook_contents(team_id,status,updated_at DESC)",
    "CREATE INDEX idx_playbook_placements_folder_order ON playbook_content_folders(folder_id,sort_order,content_id)",
    "CREATE INDEX idx_playbook_aliases_alias ON playbook_content_aliases(alias)",
    "CREATE INDEX idx_playbook_relations_target ON playbook_content_relations(target_content_id,relation_type)",
    "CREATE INDEX idx_playbook_attachments_content ON playbook_attachments(content_id,id)",
    "CREATE INDEX idx_playbook_recent_user_time ON playbook_recent_views(user_id,last_viewed_at DESC)",
    "CREATE INDEX idx_playbook_plan_items_plan_order ON playbook_training_plan_items(plan_id,sort_order,id)",
    "CREATE INDEX idx_playbook_transfers_from_event ON playbook_plan_transfers(from_event_id,transferred_at DESC)",
    "CREATE INDEX idx_playbook_evaluations_event ON playbook_plan_evaluations(calendar_event_id,content_id)",
)
MIGRATION_V8_NAME = "playbook_library_and_training_plans"
MIGRATION_V8_CHECKSUM = _migration_checksum(
    8,
    MIGRATION_V8_NAME,
    SCHEMA_V8_STATEMENTS,
    conditional_steps=(),
    canonical_contract={
        "folders": "dynamic-permanent-ids",
        "content": "versioned-multi-folder",
        "media": "metadata-only-with-protected-local-storage",
        "plans": "calendar-reference-no-event-duplication",
        "reschedule": "transactional-transfer-audited",
        "cycles": "out-of-scope",
    },
)
KNOWN_MIGRATIONS[8] = (MIGRATION_V8_NAME, MIGRATION_V8_CHECKSUM)

SCHEMA_V9_STATEMENTS = (
    "ALTER TABLE calendar_events ADD COLUMN is_countdown_target INTEGER NOT NULL DEFAULT 0 CHECK(is_countdown_target IN(0,1) AND (is_countdown_target=0 OR event_type='CHAMPIONSHIP'))",
    "CREATE UNIQUE INDEX idx_calendar_events_countdown_target ON calendar_events(team_id,season_id) WHERE is_countdown_target=1",
)
MIGRATION_V9_NAME = "calendar_countdown_targets"
MIGRATION_V9_CHECKSUM = _migration_checksum(
    9,
    MIGRATION_V9_NAME,
    SCHEMA_V9_STATEMENTS,
    conditional_steps=(),
    canonical_contract={
        "countdown_target": "one-championship-per-team-season",
        "training_count": "planned-or-confirmed-before-target",
    },
)
KNOWN_MIGRATIONS[9] = (MIGRATION_V9_NAME, MIGRATION_V9_CHECKSUM)

# A V10 torna o planejamento uma entidade própria. As tabelas V8 são
# renomeadas durante a migração, preservando seus IDs para a cópia auditável
# dos dados; o código de migração abaixo materializa planos, sessões e seus
# vínculos opcionais com o calendário sem alterar eventos ou chamadas.
SCHEMA_V10_STATEMENTS = (
    "ALTER TABLE calendar_events ADD COLUMN is_player_visible INTEGER NOT NULL DEFAULT 0 CHECK(is_player_visible IN(0,1))",
    "CREATE INDEX idx_calendar_events_player_visible ON calendar_events(team_id,season_id,starts_at) WHERE is_player_visible=1",
    "ALTER TABLE playbook_training_plan_items RENAME TO playbook_training_plan_items_v8",
    "ALTER TABLE playbook_plan_transfers RENAME TO playbook_plan_transfers_v8",
    "ALTER TABLE playbook_plan_evaluations RENAME TO playbook_plan_evaluations_v8",
    "ALTER TABLE playbook_training_plans RENAME TO playbook_training_plans_v8",
    "CREATE TABLE playbook_training_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '', seasonal_objective TEXT NOT NULL DEFAULT '', context_adjustment TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN('ACTIVE','ARCHIVED')), current_revision INTEGER NOT NULL DEFAULT 1 CHECK(current_revision>=1), created_by_user_id INTEGER NOT NULL, updated_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE RESTRICT, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(updated_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_training_plan_revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER NOT NULL, revision_number INTEGER NOT NULL CHECK(revision_number>=1), snapshot_json TEXT NOT NULL, change_summary TEXT NOT NULL DEFAULT '', restored_from_revision_id INTEGER, created_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(plan_id,revision_number), FOREIGN KEY(plan_id) REFERENCES playbook_training_plans(id) ON DELETE CASCADE, FOREIGN KEY(restored_from_revision_id) REFERENCES playbook_training_plan_revisions(id) ON DELETE SET NULL, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_training_plan_items (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER NOT NULL, content_id INTEGER NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, planned_minutes INTEGER CHECK(planned_minutes IS NULL OR planned_minutes>0), notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(plan_id,content_id), FOREIGN KEY(plan_id) REFERENCES playbook_training_plans(id) ON DELETE CASCADE, FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_series (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL, plan_id INTEGER, title TEXT NOT NULL DEFAULT '', recurrence_rule TEXT NOT NULL DEFAULT '', starts_on TEXT, ends_on TEXT, notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN('ACTIVE','ARCHIVED')), created_by_user_id INTEGER NOT NULL, updated_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE RESTRICT, FOREIGN KEY(plan_id) REFERENCES playbook_training_plans(id) ON DELETE SET NULL, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(updated_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL, plan_id INTEGER NOT NULL, series_id INTEGER, title_override TEXT NOT NULL DEFAULT '', starts_at TEXT, ends_at TEXT, local_overrides_json TEXT NOT NULL DEFAULT '{}', execution_status TEXT NOT NULL DEFAULT 'NOT_STARTED' CHECK(execution_status IN('NOT_STARTED','IN_PROGRESS','COMPLETED','CANCELLED')), execution_notes TEXT NOT NULL DEFAULT '', current_revision INTEGER NOT NULL DEFAULT 1 CHECK(current_revision>=1), created_by_user_id INTEGER NOT NULL, updated_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, CHECK(ends_at IS NULL OR starts_at IS NULL OR ends_at>starts_at), FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE RESTRICT, FOREIGN KEY(plan_id) REFERENCES playbook_training_plans(id) ON DELETE RESTRICT, FOREIGN KEY(series_id) REFERENCES playbook_series(id) ON DELETE SET NULL, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(updated_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_session_revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, revision_number INTEGER NOT NULL CHECK(revision_number>=1), snapshot_json TEXT NOT NULL, change_summary TEXT NOT NULL DEFAULT '', restored_from_revision_id INTEGER, created_by_user_id INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(session_id,revision_number), FOREIGN KEY(session_id) REFERENCES playbook_sessions(id) ON DELETE CASCADE, FOREIGN KEY(restored_from_revision_id) REFERENCES playbook_session_revisions(id) ON DELETE SET NULL, FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_session_event_links (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, calendar_event_id INTEGER NOT NULL, link_state TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(link_state IN('ACTIVE','HISTORICAL')), link_order INTEGER NOT NULL DEFAULT 0, linked_by_user_id INTEGER NOT NULL, linked_at TEXT NOT NULL, unlinked_by_user_id INTEGER, unlinked_at TEXT, unlink_reason TEXT NOT NULL DEFAULT '', FOREIGN KEY(session_id) REFERENCES playbook_sessions(id) ON DELETE RESTRICT, FOREIGN KEY(calendar_event_id) REFERENCES calendar_events(id) ON DELETE RESTRICT, FOREIGN KEY(linked_by_user_id) REFERENCES users(id) ON DELETE RESTRICT, FOREIGN KEY(unlinked_by_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_session_event_history (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, from_event_id INTEGER, to_event_id INTEGER, action TEXT NOT NULL CHECK(action IN('LINK','UNLINK','RESCHEDULE','MERGE','MIGRATE')), reason TEXT NOT NULL DEFAULT '', actor_user_id INTEGER NOT NULL, occurred_at TEXT NOT NULL, FOREIGN KEY(session_id) REFERENCES playbook_sessions(id) ON DELETE RESTRICT, FOREIGN KEY(from_event_id) REFERENCES calendar_events(id) ON DELETE RESTRICT, FOREIGN KEY(to_event_id) REFERENCES calendar_events(id) ON DELETE RESTRICT, FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE TABLE playbook_session_evaluations (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, calendar_event_id INTEGER, content_id INTEGER NOT NULL, mastery_stage TEXT NOT NULL CHECK(mastery_stage IN('STARTING','IMPROVING','REFINING','CONSOLIDATED')), continuity_decision TEXT NOT NULL CHECK(continuity_decision IN('CONTINUE','COMPLETE','REVIEW')), notes TEXT NOT NULL DEFAULT '', actor_user_id INTEGER NOT NULL, evaluated_at TEXT NOT NULL, FOREIGN KEY(session_id) REFERENCES playbook_sessions(id) ON DELETE RESTRICT, FOREIGN KEY(calendar_event_id) REFERENCES calendar_events(id) ON DELETE SET NULL, FOREIGN KEY(content_id) REFERENCES playbook_contents(id) ON DELETE RESTRICT, FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE RESTRICT)",
    "CREATE INDEX idx_playbook_plans_team_updated ON playbook_training_plans(team_id,status,updated_at DESC)",
    "CREATE INDEX idx_playbook_plan_revisions_plan_number ON playbook_training_plan_revisions(plan_id,revision_number DESC)",
    "CREATE INDEX idx_playbook_plan_items_v10_plan_order ON playbook_training_plan_items(plan_id,sort_order,id)",
    "CREATE INDEX idx_playbook_series_team_status ON playbook_series(team_id,status,updated_at DESC)",
    "CREATE INDEX idx_playbook_sessions_team_schedule ON playbook_sessions(team_id,starts_at,id)",
    "CREATE INDEX idx_playbook_sessions_plan ON playbook_sessions(plan_id,created_at DESC)",
    "CREATE INDEX idx_playbook_session_revisions_session_number ON playbook_session_revisions(session_id,revision_number DESC)",
    "CREATE UNIQUE INDEX idx_playbook_session_event_one_active ON playbook_session_event_links(session_id) WHERE link_state='ACTIVE'",
    "CREATE INDEX idx_playbook_session_event_event_order ON playbook_session_event_links(calendar_event_id,link_state,link_order,id)",
    "CREATE INDEX idx_playbook_session_event_history_session_time ON playbook_session_event_history(session_id,occurred_at,id)",
    "CREATE INDEX idx_playbook_session_evaluations_session_content ON playbook_session_evaluations(session_id,content_id,evaluated_at DESC)",
)
MIGRATION_V10_NAME = "playbook_independent_plans_and_player_calendar_visibility"
MIGRATION_V10_CHECKSUM = _migration_checksum(
    10,
    MIGRATION_V10_NAME,
    SCHEMA_V10_STATEMENTS,
    conditional_steps=(
        {
            "condition": "V8 playbook tables contain event-centric records",
            "sql": "copy-v8-event-plans-to-independent-plans-and-sessions",
        },
    ),
    canonical_contract={
        "plans": "independent-versioned-reusable",
        "series": "future-sessions-without-calendar-ownership",
        "sessions": "optional-calendar-links-many-sessions-per-event",
        "reschedule": "move-links-preserve-history-and-order",
        "calendar_visibility": "private-by-default-player-visible-explicitly",
    },
)
KNOWN_MIGRATIONS[10] = (MIGRATION_V10_NAME, MIGRATION_V10_CHECKSUM)

# O instante efetivo é separado do instante de cada clique. A trilha de
# auditoria continua imutável e torna explícita a restauração de uma decisão
# anterior quando a pessoa volta ao mesmo estado em até três horas.
SCHEMA_V11_STATEMENTS = (
    "ALTER TABLE attendance_records ADD COLUMN confirmation_decided_at TEXT",
    "UPDATE attendance_records SET confirmation_decided_at=updated_at WHERE confirmation_decided_at IS NULL AND confirmation_status<>'PENDING'",
    "ALTER TABLE attendance_audit_log ADD COLUMN old_confirmation_decided_at TEXT",
    "ALTER TABLE attendance_audit_log ADD COLUMN new_confirmation_decided_at TEXT",
    "ALTER TABLE attendance_audit_log ADD COLUMN decision_timing_note TEXT",
    "CREATE INDEX idx_attendance_audit_member_changed ON attendance_audit_log(session_id,member_id,changed_at DESC,id DESC)",
)
MIGRATION_V11_NAME = "attendance_effective_decision_timing"
MIGRATION_V11_CHECKSUM = _migration_checksum(
    11,
    MIGRATION_V11_NAME,
    SCHEMA_V11_STATEMENTS,
    conditional_steps=(),
    canonical_contract={
        "effective_decision": "first-decision-restored-on-return-within-3-hours",
        "audit": "every-click-kept-with-effective-timing-note",
    },
)
KNOWN_MIGRATIONS[11] = (MIGRATION_V11_NAME, MIGRATION_V11_CHECKSUM)

V5_PERMISSION_GRANT_LAYOUT: tuple[ColumnContract, ...] = (
    ("user_id", "INTEGER", True, None, 1),
    ("permission_code", "TEXT", True, None, 2),
    ("granted_by_user_id", "INTEGER", True, None, 0),
    ("granted_at", "TEXT", True, None, 0),
)
V5_PERMISSION_GRANT_FOREIGN_KEYS = frozenset({
    ("user_id", "users", "id", "NO ACTION", "CASCADE", "NONE"),
    ("granted_by_user_id", "users", "id", "NO ACTION", "RESTRICT", "NONE"),
})
V5_PERMISSION_GRANT_SQL_FRAGMENTS = (
    "check(permission_codein('sql.explore','sql.admin'))",
)
V5_PERMISSION_GRANT_INDEX = (
    "idx_user_permission_grants_actor",
    "user_permission_grants",
    ("granted_by_user_id", "granted_at"),
)

V3_REQUIRED_COLUMNS = {
    "calendar_events": {
        "id",
        "team_id",
        "season_id",
        "event_type",
        "status",
        "starts_at",
        "ends_at",
        "location",
        "notes",
        "restriction_kind",
        "attendance_session_id",
        "created_by_user_id",
        "updated_by_user_id",
        "created_at",
        "updated_at",
    },
    "calendar_justifications": {
        "id",
        "event_id",
        "player_member_id",
        "reason",
        "created_by_user_id",
        "updated_by_user_id",
        "created_at",
        "updated_at",
    },
}

V8_REQUIRED_COLUMNS = {
    "playbook_folders": {"id", "team_id", "parent_id", "name", "sort_order", "archived_at"},
    "playbook_contents": {"id", "team_id", "title", "status", "current_revision", "published_at"},
    "playbook_content_revisions": {"id", "content_id", "revision_number", "snapshot_json"},
    "playbook_content_folders": {"content_id", "folder_id", "placement_kind", "sort_order"},
    "playbook_content_aliases": {"content_id", "alias"},
    "playbook_content_positions": {"content_id", "position"},
    "playbook_content_relations": {"id", "source_content_id", "target_content_id", "relation_type"},
    "playbook_attachments": {"id", "content_id", "storage_kind", "url", "storage_key", "offline_essential"},
    "playbook_favorites": {"user_id", "content_id"},
    "playbook_recent_views": {"user_id", "content_id", "last_viewed_at"},
    "playbook_training_plans": {"id", "calendar_event_id", "team_id", "seasonal_objective", "context_adjustment"},
    "playbook_training_plan_items": {"id", "plan_id", "content_id", "sort_order"},
    "playbook_plan_transfers": {"id", "plan_id", "from_event_id", "to_event_id"},
    "playbook_plan_evaluations": {"id", "calendar_event_id", "content_id", "mastery_stage", "continuity_decision"},
}

V9_REQUIRED_COLUMNS = {
    "calendar_events": {"is_countdown_target"},
}

V10_REQUIRED_COLUMNS = {
    "calendar_events": {"is_player_visible"},
    "playbook_training_plans": {
        "id",
        "team_id",
        "title",
        "seasonal_objective",
        "context_adjustment",
        "notes",
        "status",
        "current_revision",
    },
    "playbook_training_plan_revisions": {
        "id",
        "plan_id",
        "revision_number",
        "snapshot_json",
        "change_summary",
    },
    "playbook_training_plan_items": {
        "id",
        "plan_id",
        "content_id",
        "sort_order",
        "planned_minutes",
        "updated_at",
    },
    "playbook_series": {
        "id",
        "team_id",
        "plan_id",
        "recurrence_rule",
        "status",
    },
    "playbook_sessions": {
        "id",
        "team_id",
        "plan_id",
        "series_id",
        "starts_at",
        "ends_at",
        "local_overrides_json",
        "execution_status",
    },
    "playbook_session_revisions": {
        "id",
        "session_id",
        "revision_number",
        "snapshot_json",
    },
    "playbook_session_event_links": {
        "id",
        "session_id",
        "calendar_event_id",
        "link_state",
        "link_order",
    },
    "playbook_session_event_history": {
        "id",
        "session_id",
        "from_event_id",
        "to_event_id",
        "action",
    },
    "playbook_session_evaluations": {
        "id",
        "session_id",
        "calendar_event_id",
        "content_id",
        "mastery_stage",
    },
}


def _apply_schema_v4(conn: sqlite3.Connection) -> None:
    duplicates = _fetchall(
        conn,
        """SELECT attendance_session_id FROM calendar_events
           WHERE attendance_session_id IS NOT NULL
           GROUP BY attendance_session_id HAVING COUNT(*) > 1""",
    )
    if duplicates:
        ids = ", ".join(str(row[0]) for row in duplicates)
        raise DatabaseSchemaError(
            "Migração recusada: uma chamada está vinculada a mais de um evento "
            f"de calendário ({ids})."
        )
    conn.execute(
        """CREATE TABLE training_sessions_v4 (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               training_date TEXT NOT NULL,
               notes TEXT NOT NULL DEFAULT '',
               is_finalized INTEGER NOT NULL DEFAULT 0
                   CHECK (is_finalized IN (0, 1)),
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           )"""
    )
    conn.execute(
        """INSERT INTO training_sessions_v4(
               id,training_date,notes,is_finalized,created_at,updated_at
           ) SELECT id,training_date,notes,is_finalized,created_at,updated_at
             FROM training_sessions"""
    )
    conn.execute("DROP TABLE training_sessions")
    conn.execute("ALTER TABLE training_sessions_v4 RENAME TO training_sessions")
    conn.execute(
        "CREATE INDEX idx_training_date ON training_sessions(training_date)"
    )
    conn.execute(
        """CREATE UNIQUE INDEX idx_calendar_events_attendance_session
           ON calendar_events(attendance_session_id)
           WHERE attendance_session_id IS NOT NULL"""
    )


def _record_schema_v4(conn: sqlite3.Connection, *, app_version: str, origin: str) -> None:
    conn.execute(
        """INSERT INTO schema_migrations(
               version,name,checksum_sha256,applied_at,app_version,origin
           ) VALUES(?,?,?,?,?,?)""",
        (
            4,
            MIGRATION_V4_NAME,
            MIGRATION_V4_CHECKSUM,
            _now_iso(),
            app_version,
            origin,
        ),
    )
    conn.execute("PRAGMA user_version = 4").close()


def _apply_schema_v5(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_V5_STATEMENTS:
        conn.execute(statement)


def _apply_schema_v6(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_V6_STATEMENTS:
        conn.execute(statement)


def _apply_schema_v7(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_V7_STATEMENTS:
        conn.execute(statement)


def _apply_schema_v8(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_V8_STATEMENTS:
        conn.execute(statement)


def _apply_schema_v9(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_V9_STATEMENTS:
        conn.execute(statement)


def _apply_schema_v11(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_V11_STATEMENTS:
        conn.execute(statement)


def _v10_snapshot(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _apply_schema_v10(conn: sqlite3.Connection) -> None:
    """Aplica o modelo independente e copia integralmente o modelo V8.

    A V8 prendia um plano a um único evento. Em vez de descartar ou reescrever
    os registros antigos, a V10 conserva os IDs de plano/item/transferência/
    avaliação e cria uma sessão inicial para cada plano legado. O evento passa
    a ser apenas um vínculo opcional da sessão.
    """

    for statement in SCHEMA_V10_STATEMENTS:
        conn.execute(statement)

    legacy_plans = _fetchall(
        conn,
        "SELECT * FROM playbook_training_plans_v8 ORDER BY id",
    )
    for legacy_plan in legacy_plans:
        plan = dict(legacy_plan)
        legacy_items = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM playbook_training_plan_items_v8 WHERE plan_id=? "
                "ORDER BY sort_order,id",
                (plan["id"],),
            ).fetchall()
        ]
        event = _fetchone(
            conn,
            "SELECT id,status,starts_at,ends_at FROM calendar_events WHERE id=?",
            (plan["calendar_event_id"],),
        )
        if event is None:
            raise DatabaseSchemaError(
                "Migração V10 recusada: plano V8 "
                f"{plan['id']} referencia evento inexistente."
            )
        event_data = dict(event)
        conn.execute(
            """INSERT INTO playbook_training_plans(
                   id,team_id,title,seasonal_objective,context_adjustment,notes,
                   status,current_revision,created_by_user_id,updated_by_user_id,
                   created_at,updated_at
               ) VALUES(?,?,?,?,?,'','ACTIVE',1,?,?,?,?)""",
            (
                plan["id"],
                plan["team_id"],
                plan["title"],
                plan["seasonal_objective"],
                plan["context_adjustment"],
                plan["created_by_user_id"],
                plan["updated_by_user_id"],
                plan["created_at"],
                plan["updated_at"],
            ),
        )
        # A coluna notes está no SELECT V8 e precisa ser mantida, mas a forma
        # compacta acima evita duplicar a lista de colunas no INSERT inicial.
        conn.execute(
            "UPDATE playbook_training_plans SET notes=? WHERE id=?",
            (plan["notes"], plan["id"]),
        )
        conn.execute(
            """INSERT INTO playbook_training_plan_revisions(
                   plan_id,revision_number,snapshot_json,change_summary,
                   restored_from_revision_id,created_by_user_id,created_at
               ) VALUES(?,?,?,?,NULL,?,?)""",
            (
                plan["id"],
                1,
                _v10_snapshot(
                    {
                        "source": "v8-event-centric-plan",
                        "plan": {
                            "title": plan["title"],
                            "seasonal_objective": plan["seasonal_objective"],
                            "context_adjustment": plan["context_adjustment"],
                            "notes": plan["notes"],
                        },
                        "items": legacy_items,
                    }
                ),
                "Migração automática PB-3B a partir do plano V8.",
                plan["created_by_user_id"],
                plan["created_at"],
            ),
        )
        for item in legacy_items:
            conn.execute(
                """INSERT INTO playbook_training_plan_items(
                       id,plan_id,content_id,sort_order,planned_minutes,notes,
                       created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    item["id"],
                    item["plan_id"],
                    item["content_id"],
                    item["sort_order"],
                    item["planned_minutes"],
                    item["notes"],
                    item["created_at"],
                    plan["updated_at"],
                ),
            )
        execution_status = {
            "COMPLETED": "COMPLETED",
            "CANCELLED": "CANCELLED",
            "RESCHEDULED": "CANCELLED",
        }.get(str(event_data["status"]), "NOT_STARTED")
        conn.execute(
            """INSERT INTO playbook_sessions(
                   id,team_id,plan_id,series_id,title_override,starts_at,ends_at,
                   local_overrides_json,execution_status,execution_notes,
                   current_revision,created_by_user_id,updated_by_user_id,
                   created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,'{}',?,'',1,?,?,?,?)""",
            (
                plan["id"],
                plan["team_id"],
                plan["id"],
                None,
                plan["title"],
                event_data["starts_at"],
                event_data["ends_at"],
                execution_status,
                plan["created_by_user_id"],
                plan["updated_by_user_id"],
                plan["created_at"],
                plan["updated_at"],
            ),
        )
        session_snapshot = {
            "source": "v8-event-centric-plan",
            "plan_id": plan["id"],
            "title_override": plan["title"],
            "starts_at": event_data["starts_at"],
            "ends_at": event_data["ends_at"],
            "execution_status": execution_status,
        }
        conn.execute(
            """INSERT INTO playbook_session_revisions(
                   session_id,revision_number,snapshot_json,change_summary,
                   restored_from_revision_id,created_by_user_id,created_at
               ) VALUES(?,?,?,?,NULL,?,?)""",
            (
                plan["id"],
                1,
                _v10_snapshot(session_snapshot),
                "Migração automática PB-3B da sessão vinculada ao evento V8.",
                plan["created_by_user_id"],
                plan["created_at"],
            ),
        )
        link_state = (
            "HISTORICAL"
            if event_data["status"] in {"CANCELLED", "RESCHEDULED"}
            else "ACTIVE"
        )
        conn.execute(
            """INSERT INTO playbook_session_event_links(
                   session_id,calendar_event_id,link_state,link_order,
                   linked_by_user_id,linked_at
               ) VALUES(?,?,?,?,?,?)""",
            (
                plan["id"],
                plan["calendar_event_id"],
                link_state,
                0,
                plan["updated_by_user_id"],
                plan["updated_at"],
            ),
        )

    legacy_transfers = _fetchall(
        conn,
        "SELECT * FROM playbook_plan_transfers_v8 ORDER BY id",
    )
    for transfer_row in legacy_transfers:
        transfer = dict(transfer_row)
        conn.execute(
            """INSERT INTO playbook_session_event_history(
                   id,session_id,from_event_id,to_event_id,action,reason,
                   actor_user_id,occurred_at
               ) VALUES(?,?,?,?,'RESCHEDULE',?,?,?)""",
            (
                transfer["id"],
                transfer["plan_id"],
                transfer["from_event_id"],
                transfer["to_event_id"],
                transfer["reason"],
                transfer["actor_user_id"],
                transfer["transferred_at"],
            ),
        )
        for event_id in (transfer["from_event_id"], transfer["to_event_id"]):
            existing_link = _fetchone(
                conn,
                """SELECT id FROM playbook_session_event_links
                   WHERE session_id=? AND calendar_event_id=? LIMIT 1""",
                (transfer["plan_id"], event_id),
            )
            if existing_link is None:
                conn.execute(
                    """INSERT INTO playbook_session_event_links(
                           session_id,calendar_event_id,link_state,link_order,
                           linked_by_user_id,linked_at,unlink_reason
                       ) VALUES(?,?, 'HISTORICAL', ?, ?, ?, ?)""",
                    (
                        transfer["plan_id"],
                        event_id,
                        transfer["id"],
                        transfer["actor_user_id"],
                        transfer["transferred_at"],
                        "Vínculo histórico migrado da transferência V8.",
                    ),
                )

    legacy_evaluations = _fetchall(
        conn,
        "SELECT * FROM playbook_plan_evaluations_v8 ORDER BY id",
    )
    for evaluation_row in legacy_evaluations:
        evaluation = dict(evaluation_row)
        source_plan = _fetchone(
            conn,
            """SELECT id FROM playbook_training_plans_v8
               WHERE calendar_event_id=? ORDER BY id LIMIT 1""",
            (evaluation["calendar_event_id"],),
        )
        if source_plan is None:
            source_plan = _fetchone(
                conn,
                """SELECT plan_id AS id FROM playbook_plan_transfers_v8
                   WHERE from_event_id=? OR to_event_id=?
                   ORDER BY transferred_at DESC,id DESC LIMIT 1""",
                (evaluation["calendar_event_id"], evaluation["calendar_event_id"]),
            )
        if source_plan is None:
            raise DatabaseSchemaError(
                "Migração V10 recusada: avaliação V8 "
                f"{evaluation['id']} não possui plano de origem preservável."
            )
        conn.execute(
            """INSERT INTO playbook_session_evaluations(
                   id,session_id,calendar_event_id,content_id,mastery_stage,
                   continuity_decision,notes,actor_user_id,evaluated_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                evaluation["id"],
                source_plan["id"],
                evaluation["calendar_event_id"],
                evaluation["content_id"],
                evaluation["mastery_stage"],
                evaluation["continuity_decision"],
                evaluation["notes"],
                evaluation["actor_user_id"],
                evaluation["evaluated_at"],
            ),
        )


def _record_schema_v5(conn: sqlite3.Connection, *, app_version: str, origin: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations(version,name,checksum_sha256,applied_at,app_version,origin) VALUES(?,?,?,?,?,?)",
        (5, MIGRATION_V5_NAME, MIGRATION_V5_CHECKSUM, _now_iso(), app_version, origin),
    )
    conn.execute("PRAGMA user_version = 5").close()


def _record_schema_v6(conn: sqlite3.Connection, *, app_version: str, origin: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations(version,name,checksum_sha256,applied_at,app_version,origin) VALUES(?,?,?,?,?,?)",
        (6, MIGRATION_V6_NAME, MIGRATION_V6_CHECKSUM, _now_iso(), app_version, origin),
    )
    conn.execute("PRAGMA user_version = 6").close()


def _record_schema_v7(conn: sqlite3.Connection, *, app_version: str, origin: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations(version,name,checksum_sha256,applied_at,app_version,origin) VALUES(?,?,?,?,?,?)",
        (7, MIGRATION_V7_NAME, MIGRATION_V7_CHECKSUM, _now_iso(), app_version, origin),
    )
    conn.execute("PRAGMA user_version = 7").close()


def _record_schema_v8(conn: sqlite3.Connection, *, app_version: str, origin: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations(version,name,checksum_sha256,applied_at,app_version,origin) VALUES(?,?,?,?,?,?)",
        (8, MIGRATION_V8_NAME, MIGRATION_V8_CHECKSUM, _now_iso(), app_version, origin),
    )
    conn.execute("PRAGMA user_version = 8").close()


def _record_schema_v9(conn: sqlite3.Connection, *, app_version: str, origin: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations(version,name,checksum_sha256,applied_at,app_version,origin) VALUES(?,?,?,?,?,?)",
        (9, MIGRATION_V9_NAME, MIGRATION_V9_CHECKSUM, _now_iso(), app_version, origin),
    )
    conn.execute("PRAGMA user_version = 9").close()


def _record_schema_v10(conn: sqlite3.Connection, *, app_version: str, origin: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations(version,name,checksum_sha256,applied_at,app_version,origin) VALUES(?,?,?,?,?,?)",
        (10, MIGRATION_V10_NAME, MIGRATION_V10_CHECKSUM, _now_iso(), app_version, origin),
    )
    conn.execute("PRAGMA user_version = 10").close()


def _record_schema_v11(conn: sqlite3.Connection, *, app_version: str, origin: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations(version,name,checksum_sha256,applied_at,app_version,origin) VALUES(?,?,?,?,?,?)",
        (11, MIGRATION_V11_NAME, MIGRATION_V11_CHECKSUM, _now_iso(), app_version, origin),
    )
    conn.execute("PRAGMA user_version = 11").close()


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
    if table == "attendance_records":
        allowed_layouts.add(
            expected + (("confirmation_decided_at", "TEXT", False, None, 0),)
        )
    if table == "attendance_audit_log":
        v11_layout = expected + (
            ("old_confirmation_decided_at", "TEXT", False, None, 0),
            ("new_confirmation_decided_at", "TEXT", False, None, 0),
            ("decision_timing_note", "TEXT", False, None, 0),
        )
        allowed_layouts.add(v11_layout)
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
    allow_multiple_training_same_day: bool = False,
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
        if table == "training_sessions" and allow_multiple_training_same_day:
            expected_unique = frozenset()
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
        base_problems = _schema_problems(
            conn,
            allow_multiple_training_same_day=current_version >= 4,
        )
        if current_version >= 2:
            base_problems = [problem for problem in base_problems if not (
                "attendance_audit_log" in problem and (
                    "Colunas inesperadas" in problem or "Chaves estrangeiras divergentes" in problem
                )
            )]
            required_v2 = {"people", "users", "teams", "seasons", "team_memberships", "membership_roles", "system_roles", "player_user_links", "auth_sessions", "security_audit_events"}
            missing_v2 = required_v2 - tables
            base_problems.extend(f"Tabela HM-IME obrigatória ausente: {table}." for table in sorted(missing_v2))
            for table, required_columns in V2_REQUIRED_COLUMNS.items():
                if table in tables:
                    missing_columns = required_columns - _columns(conn, table)
                    if missing_columns:
                        base_problems.append(
                            f"Colunas HM-IME ausentes em {table}: "
                            + ", ".join(sorted(missing_columns))
                            + "."
                        )
        if current_version >= 3:
            required_v3 = set(V3_REQUIRED_COLUMNS)
            missing_v3 = required_v3 - tables
            base_problems.extend(
                f"Tabela Calendário obrigatória ausente: {table}."
                for table in sorted(missing_v3)
            )
            for table, required_columns in V3_REQUIRED_COLUMNS.items():
                if table in tables:
                    missing_columns = required_columns - _columns(conn, table)
                    if missing_columns:
                        base_problems.append(
                            f"Colunas Calendário ausentes em {table}: "
                            + ", ".join(sorted(missing_columns))
                            + "."
                        )
        if current_version >= 4:
            index_rows = _fetchall(
                conn,
                "PRAGMA index_list(calendar_events)",
            )
            if not any(
                str(row["name"]) == "idx_calendar_events_attendance_session"
                and bool(row["unique"])
                for row in index_rows
            ):
                base_problems.append(
                    "Índice único de vínculo Calendário-Presenças ausente."
                )
        if current_version >= 5:
            if "user_permission_grants" not in tables:
                base_problems.append(
                    "Tabela de concessões individuais de permissão ausente."
                )
            else:
                base_problems.extend(
                    _column_layout_problems(
                        conn,
                        "user_permission_grants",
                        V5_PERMISSION_GRANT_LAYOUT,
                    )
                )
                if _unique_constraints(conn, "user_permission_grants"):
                    base_problems.append(
                        "Restrições UNIQUE inesperadas em user_permission_grants."
                    )
                if (
                    _foreign_keys(conn, "user_permission_grants")
                    != V5_PERMISSION_GRANT_FOREIGN_KEYS
                ):
                    base_problems.append(
                        "Chaves estrangeiras divergentes em user_permission_grants."
                    )
                normalized_sql = _normalized_table_sql(
                    conn, "user_permission_grants"
                )
                for fragment in V5_PERMISSION_GRANT_SQL_FRAGMENTS:
                    if fragment not in normalized_sql:
                        base_problems.append(
                            "Restrição CHECK divergente em user_permission_grants."
                        )
                index_name, index_table, index_columns = V5_PERMISSION_GRANT_INDEX
                index_problem = _named_index_problem(
                    conn, index_name, index_table, index_columns
                )
                if index_problem:
                    base_problems.append(index_problem)
        if current_version >= 6:
            required_v6 = {"attendance_record_positions"}
            base_problems.extend(
                f"Tabela de posições por treino ausente: {table}."
                for table in sorted(required_v6 - tables)
            )
        if current_version >= 7:
            required_v7 = {
                "calendar_event_series",
                "calendar_event_transitions",
                "calendar_command_receipts",
            }
            base_problems.extend(
                f"Tabela do Calendário profissional ausente: {table}."
                for table in sorted(required_v7 - tables)
            )
            if "calendar_events" in tables:
                missing_columns = {
                    "title",
                    "opponent",
                    "all_day",
                    "version",
                    "series_id",
                } - _columns(conn, "calendar_events")
                if missing_columns:
                    base_problems.append(
                        "Colunas do Calendário profissional ausentes em "
                        "calendar_events: "
                        + ", ".join(sorted(missing_columns))
                        + "."
                    )
        if 8 <= current_version < 10:
            required_v8 = set(V8_REQUIRED_COLUMNS)
            base_problems.extend(
                f"Tabela do Playbook obrigatória ausente: {table}."
                for table in sorted(required_v8 - tables)
            )
            for table, required_columns in V8_REQUIRED_COLUMNS.items():
                if table not in tables:
                    continue
                missing_columns = required_columns - _columns(conn, table)
                if missing_columns:
                    base_problems.append(
                        f"Colunas do Playbook ausentes em {table}: "
                        + ", ".join(sorted(missing_columns))
                        + "."
                    )
        if current_version >= 9:
            for table, required_columns in V9_REQUIRED_COLUMNS.items():
                if table not in tables:
                    continue
                missing_columns = required_columns - _columns(conn, table)
                if missing_columns:
                    base_problems.append(
                        f"Colunas do contador ausentes em {table}: "
                        + ", ".join(sorted(missing_columns))
                        + "."
                    )
        if current_version >= 10:
            required_v10 = set(V10_REQUIRED_COLUMNS)
            base_problems.extend(
                f"Tabela PB-3B obrigatória ausente: {table}."
                for table in sorted(required_v10 - tables)
            )
            for table, required_columns in V10_REQUIRED_COLUMNS.items():
                if table not in tables:
                    continue
                missing_columns = required_columns - _columns(conn, table)
                if missing_columns:
                    base_problems.append(
                        f"Colunas PB-3B ausentes em {table}: "
                        + ", ".join(sorted(missing_columns))
                        + "."
                    )
        if current_version >= 11:
            required_v11_columns = {
                "attendance_records": {"confirmation_decided_at"},
                "attendance_audit_log": {
                    "old_confirmation_decided_at",
                    "new_confirmation_decided_at",
                    "decision_timing_note",
                },
            }
            for table, required_columns in required_v11_columns.items():
                missing_columns = required_columns - _columns(conn, table)
                if missing_columns:
                    base_problems.append(
                        f"Colunas de decisão efetiva ausentes em {table}: "
                        + ", ".join(sorted(missing_columns))
                        + "."
                    )
        problems.extend(base_problems)
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


def _apply_schema_v2(conn: sqlite3.Connection, *, legacy_admin: tuple[str, str]) -> None:
    for statement in SCHEMA_V2_STATEMENTS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).casefold():
                raise
    now = _now_iso()
    conn.execute("INSERT INTO teams(code,slug,display_name,active,created_at,updated_at) VALUES('HM_IME','hm-ime','HM-IME',1,?,?) ON CONFLICT(code) DO NOTHING", (now, now))
    team_id = conn.execute("SELECT id FROM teams WHERE code='HM_IME'").fetchone()[0]
    conn.execute("INSERT INTO seasons(team_id,label,starts_on,ends_on,active) VALUES(?,'2026.2',NULL,NULL,1) ON CONFLICT(team_id,label) DO NOTHING", (team_id,))
    season_id = conn.execute("SELECT id FROM seasons WHERE team_id=? AND label='2026.2'", (team_id,)).fetchone()[0]
    for member in conn.execute("SELECT id,name FROM team_members").fetchall():
        conn.execute("INSERT INTO people(full_name,display_name,active,created_at,updated_at) VALUES(?,?,1,?,?)", (member["name"], member["name"], now, now))
        person_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO player_user_links(team_member_id,person_id,user_id) VALUES(?,?,NULL)", (member["id"], person_id))
        conn.execute("INSERT INTO team_memberships(person_id,team_id,season_id,status,valid_from,valid_to,created_at,updated_at) VALUES(?,?,?,'ACTIVE',NULL,NULL,?,?)", (person_id, team_id, season_id, now, now))
        membership_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO membership_roles(membership_id,role_code) VALUES(?,'PLAYER')", (membership_id,))
    username, password_hash = (value.strip() for value in legacy_admin)
    if not username or not password_hash:
        raise DatabaseSchemaError("A migração v2 requer username e hash administrativos válidos.")
    conn.execute("INSERT INTO people(full_name,display_name,active,created_at,updated_at) VALUES('Bob','Bob',1,?,?)", (now,now))
    person_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO users(person_id,username,password_hash,active,must_change_password,credential_version,created_at,updated_at) VALUES(?,?,?,?,0,1,?,?)", (person_id, username.casefold(), password_hash, 1, now, now))
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO system_roles(user_id,role_code) VALUES(?,'DEV'),(?,'CT')", (user_id,user_id))
    conn.execute("INSERT INTO team_memberships(person_id,team_id,season_id,status,valid_from,valid_to,created_at,updated_at) VALUES(?,?,?,'ACTIVE',NULL,NULL,?,?)", (person_id, team_id, season_id, now, now))
    membership_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO membership_roles(membership_id,role_code) VALUES(?,'CT')", (membership_id,))


def _apply_schema_v3(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_V3_STATEMENTS:
        conn.execute(statement)


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


def _record_schema_v2(conn: sqlite3.Connection, *, app_version: str, origin: str) -> None:
    conn.execute("INSERT INTO schema_migrations(version,name,checksum_sha256,applied_at,app_version,origin) VALUES(?,?,?,?,?,?)", (2,MIGRATION_V2_NAME,MIGRATION_V2_CHECKSUM,_now_iso(),app_version,origin))
    conn.execute("PRAGMA user_version = 2").close()


def _record_schema_v3(conn: sqlite3.Connection, *, app_version: str, origin: str) -> None:
    conn.execute(
        """INSERT INTO schema_migrations(
               version,name,checksum_sha256,applied_at,app_version,origin
           ) VALUES(?,?,?,?,?,?)""",
        (
            3,
            MIGRATION_V3_NAME,
            MIGRATION_V3_CHECKSUM,
            _now_iso(),
            app_version,
            origin,
        ),
    )
    conn.execute("PRAGMA user_version = 3").close()


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
        legacy_admin: tuple[str, str] | None = None,
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
        requires_v4_rebuild = False
        planning_connection = _open_read_only(self.db_path)
        try:
            planning_status = _status_from_connection(
                planning_connection,
                self.db_path,
            )
            requires_v4_rebuild = (
                planning_status.versioned
                and planning_status.current_version >= 2
                and planning_status.current_version < 4
            )
        finally:
            planning_connection.close()
        conn.execute(
            "PRAGMA foreign_keys = OFF" if requires_v4_rebuild else "PRAGMA foreign_keys = ON"
        ).close()
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
            effective_version = before.current_version
            if before.current_version < 2 and legacy_admin:
                _apply_schema_v2(conn, legacy_admin=legacy_admin)
                _record_schema_v2(conn, app_version=app_version, origin=origin)
                effective_version = 2
            if effective_version >= 2 and effective_version < 3:
                _apply_schema_v3(conn)
                _record_schema_v3(conn, app_version=app_version, origin=origin)
                effective_version = 3
            if effective_version >= 3 and effective_version < 4:
                _apply_schema_v4(conn)
                _record_schema_v4(conn, app_version=app_version, origin=origin)
                effective_version = 4
            if effective_version >= 4 and effective_version < 5:
                _apply_schema_v5(conn)
                _record_schema_v5(conn, app_version=app_version, origin=origin)
                effective_version = 5
            if effective_version >= 5 and effective_version < 6:
                _apply_schema_v6(conn)
                _record_schema_v6(conn, app_version=app_version, origin=origin)
                effective_version = 6
            if effective_version >= 6 and effective_version < 7:
                _apply_schema_v7(conn)
                _record_schema_v7(conn, app_version=app_version, origin=origin)
                effective_version = 7
            if effective_version >= 7 and effective_version < 8:
                _apply_schema_v8(conn)
                _record_schema_v8(conn, app_version=app_version, origin=origin)
                effective_version = 8
            if effective_version >= 8 and effective_version < 9:
                _apply_schema_v9(conn)
                _record_schema_v9(conn, app_version=app_version, origin=origin)
                effective_version = 9
            if effective_version >= 9 and effective_version < 10:
                _apply_schema_v10(conn)
                _record_schema_v10(conn, app_version=app_version, origin=origin)
                effective_version = 10
            if effective_version >= 10 and effective_version < 11:
                _apply_schema_v11(conn)
                _record_schema_v11(conn, app_version=app_version, origin=origin)
                effective_version = 11

            after = _status_from_connection(conn, self.db_path)
            if not after.compatible or not after.versioned or after.problems:
                raise DatabaseSchemaError(
                    "A migração não produziu um esquema versionado compatível. "
                    + " ".join(after.problems)
                )
            _verify_transaction_integrity(conn)
            conn.commit()
            if requires_v4_rebuild:
                conn.execute("PRAGMA foreign_keys = ON").close()
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
        legacy_admin: tuple[str, str] | None = None,
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
            # A v4 reconstrói a tabela de chamadas; a opção precisa ser definida
            # antes da transação, pois o SQLite não a altera dentro dela.
            conn.execute(
                "PRAGMA foreign_keys = OFF" if legacy_admin else "PRAGMA foreign_keys = ON"
            ).close()
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
            if legacy_admin:
                _apply_schema_v2(conn, legacy_admin=legacy_admin)
                _record_schema_v2(conn, app_version=app_version, origin=origin)
                _apply_schema_v3(conn)
                _record_schema_v3(conn, app_version=app_version, origin=origin)
                _apply_schema_v4(conn)
                _record_schema_v4(conn, app_version=app_version, origin=origin)
                _apply_schema_v5(conn)
                _record_schema_v5(conn, app_version=app_version, origin=origin)
                _apply_schema_v6(conn)
                _record_schema_v6(conn, app_version=app_version, origin=origin)
                _apply_schema_v7(conn)
                _record_schema_v7(conn, app_version=app_version, origin=origin)
                _apply_schema_v8(conn)
                _record_schema_v8(conn, app_version=app_version, origin=origin)
                _apply_schema_v9(conn)
                _record_schema_v9(conn, app_version=app_version, origin=origin)
                _apply_schema_v10(conn)
                _record_schema_v10(conn, app_version=app_version, origin=origin)
                _apply_schema_v11(conn)
                _record_schema_v11(conn, app_version=app_version, origin=origin)
            result = _status_from_connection(conn, self.db_path)
            if not result.compatible or not result.versioned or result.problems:
                raise DatabaseSchemaError(
                    "O bootstrap não produziu um esquema versionado compatível. "
                    + " ".join(result.problems)
                )
            _verify_transaction_integrity(conn)
            conn.commit()
            if legacy_admin:
                conn.execute("PRAGMA foreign_keys = ON").close()
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
