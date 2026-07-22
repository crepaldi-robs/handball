"""Fachada compatível para a API pública de migrations centralizada."""

from handball.database.migrations import (
    DOMAIN_TABLES,
    FINGERPRINT_FORMAT,
    KNOWN_MIGRATIONS,
    LATEST_SCHEMA_VERSION,
    MAX_SUPPORTED_SCHEMA_VERSION,
    MIGRATION_V1_CHECKSUM,
    MIGRATION_V1_NAME,
    MIN_SUPPORTED_SCHEMA_VERSION,
    DatabaseMigrator,
    DatabaseSchemaError,
    SchemaStatus,
    fingerprint_from_connection,
    logical_fingerprint,
    migration_manifest,
    verify_database,
)

__all__ = [
    "DOMAIN_TABLES",
    "FINGERPRINT_FORMAT",
    "KNOWN_MIGRATIONS",
    "LATEST_SCHEMA_VERSION",
    "MAX_SUPPORTED_SCHEMA_VERSION",
    "MIGRATION_V1_CHECKSUM",
    "MIGRATION_V1_NAME",
    "MIN_SUPPORTED_SCHEMA_VERSION",
    "DatabaseMigrator",
    "DatabaseSchemaError",
    "SchemaStatus",
    "fingerprint_from_connection",
    "logical_fingerprint",
    "migration_manifest",
    "verify_database",
]
