from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO
from uuid import uuid4


OUTPUT_FORMAT = "crepaldi-handball-database-guard/v1"
FINGERPRINT_FORMAT = "crepaldi-handball-logical-sqlite/v1"
FINGERPRINT_DOMAIN = b"crepaldi-handball-logical-sqlite/v1\x00"
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class GuardError(RuntimeError):
    """Falha operacional que pode ser comunicada sem revelar dados locais."""

    def __init__(self, code: str, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise GuardError(
            "invalid_arguments",
            "Os argumentos da operação são inválidos.",
            exit_code=2,
        )


def _emit_json(payload: dict[str, Any], stream: TextIO) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    binary_stream = getattr(stream, "buffer", None)
    if binary_stream is not None:
        binary_stream.write((serialized + "\n").encode("utf-8"))
        binary_stream.flush()
    else:
        stream.write(serialized + "\n")
        stream.flush()


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _absolute_lexical_path(path_value: str | os.PathLike[str]) -> Path:
    """Normaliza sem seguir links; a inspeção de reparse precisa vir antes do resolve."""

    return Path(os.path.abspath(os.path.normpath(os.fspath(path_value))))


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    if int(getattr(metadata, "st_file_attributes", 0)) & int(reparse_flag):
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            return bool(is_junction())
        except OSError:
            return False
    return False


def _assert_no_reparse_components(
    path: Path,
    *,
    code: str,
    message: str,
) -> None:
    absolute_path = _absolute_lexical_path(path)
    components = [*reversed(absolute_path.parents), absolute_path]
    for component in components:
        if os.path.lexists(component) and _is_reparse_point(component):
            raise GuardError(code, message)


def _normalized_path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def _resolve_required_path(
    path_value: str | os.PathLike[str],
    *,
    missing_code: str,
    missing_message: str,
    unsafe_code: str,
    unsafe_message: str,
    require_file: bool,
) -> Path:
    lexical_path = _absolute_lexical_path(path_value)
    _assert_no_reparse_components(
        lexical_path,
        code=unsafe_code,
        message=unsafe_message,
    )
    try:
        resolved_path = lexical_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GuardError(
            missing_code,
            missing_message,
        ) from exc
    if require_file and not resolved_path.is_file():
        raise GuardError(
            missing_code,
            missing_message,
        )
    if not require_file and not resolved_path.is_dir():
        raise GuardError(missing_code, missing_message)
    return resolved_path


def _resolve_database_path(
    config_path_value: str | os.PathLike[str],
    expected_database_path_value: str | os.PathLike[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    config_path = _resolve_required_path(
        config_path_value,
        missing_code="config_missing",
        missing_message="O arquivo de configuração obrigatório não existe.",
        unsafe_code="unsafe_config_path",
        unsafe_message="A configuração usa symlink, junction ou reparse point.",
        require_file=True,
    )

    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardError(
            "invalid_config",
            "O arquivo de configuração é inválido.",
        ) from exc
    if not isinstance(raw_config, dict):
        raise GuardError(
            "invalid_config",
            "O arquivo de configuração é inválido.",
        )

    db_path_value = raw_config.get("db_path")
    if not isinstance(db_path_value, str) or not db_path_value.strip():
        raise GuardError(
            "invalid_config",
            "A configuração não define um banco de dados válido.",
        )
    database_path = Path(db_path_value.strip())
    if not database_path.is_absolute():
        raise GuardError(
            "invalid_config",
            "O caminho configurado para o banco deve ser absoluto.",
        )
    database_path = _resolve_required_path(
        database_path,
        missing_code="database_missing",
        missing_message="O banco de dados obrigatório não existe.",
        unsafe_code="unsafe_database_path",
        unsafe_message="O banco usa symlink, junction ou reparse point.",
        require_file=True,
    )

    if expected_database_path_value is not None:
        expected_path = Path(expected_database_path_value)
        if not expected_path.is_absolute():
            raise GuardError(
                "invalid_expected_database_path",
                "O caminho esperado para o banco deve ser absoluto.",
                exit_code=2,
            )
        expected_path = _resolve_required_path(
            expected_path,
            missing_code="expected_database_missing",
            missing_message="O banco esperado não existe.",
            unsafe_code="unsafe_expected_database_path",
            unsafe_message="O banco esperado usa reparse point.",
            require_file=True,
        )
        if _normalized_path_key(database_path) != _normalized_path_key(expected_path):
            raise GuardError(
                "database_path_mismatch",
                "O banco configurado não corresponde ao caminho operacional esperado.",
            )
    return database_path, raw_config


def _resolve_backup_destination(
    destination_value: str | os.PathLike[str],
    *,
    raw_config: dict[str, Any],
    expected_backup_root_value: str | os.PathLike[str] | None,
) -> Path:
    destination = _absolute_lexical_path(destination_value)
    _assert_no_reparse_components(
        destination,
        code="unsafe_backup_destination",
        message="O destino do backup usa symlink, junction ou reparse point.",
    )
    destination = destination.resolve(strict=False)

    if expected_backup_root_value is None:
        return destination

    expected_root_raw = Path(expected_backup_root_value)
    if not expected_root_raw.is_absolute():
        raise GuardError(
            "invalid_expected_backup_root",
            "O diretório esperado de backups deve ser absoluto.",
            exit_code=2,
        )
    expected_root = _resolve_required_path(
        expected_root_raw,
        missing_code="expected_backup_root_missing",
        missing_message="O diretório esperado de backups não existe.",
        unsafe_code="unsafe_backup_root",
        unsafe_message="O diretório de backups usa reparse point.",
        require_file=False,
    )

    configured_root_value = raw_config.get("backup_dir")
    if not isinstance(configured_root_value, str) or not configured_root_value.strip():
        raise GuardError(
            "invalid_config",
            "A configuração não define um diretório de backups válido.",
        )
    configured_root_raw = Path(configured_root_value.strip())
    if not configured_root_raw.is_absolute():
        raise GuardError(
            "invalid_config",
            "O caminho configurado para backups deve ser absoluto.",
        )
    configured_root = _resolve_required_path(
        configured_root_raw,
        missing_code="backup_root_missing",
        missing_message="O diretório configurado de backups não existe.",
        unsafe_code="unsafe_backup_root",
        unsafe_message="O diretório de backups usa reparse point.",
        require_file=False,
    )
    if _normalized_path_key(configured_root) != _normalized_path_key(expected_root):
        raise GuardError(
            "backup_root_mismatch",
            "O diretório configurado de backups diverge do diretório esperado.",
        )

    try:
        relative_destination = destination.relative_to(expected_root)
    except ValueError as exc:
        raise GuardError(
            "backup_destination_outside_root",
            "O destino do backup está fora do diretório operacional permitido.",
        ) from exc
    if not relative_destination.parts:
        raise GuardError(
            "backup_destination_outside_root",
            "O destino do backup deve ser um arquivo dentro do diretório permitido.",
        )
    return destination


def _open_read_only(database_path: Path) -> sqlite3.Connection:
    uri = f"{database_path.as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=30,
            isolation_level=None,
            cached_statements=0,
        )
    except sqlite3.Error as exc:
        raise GuardError(
            "database_open_failed",
            "Não foi possível abrir o banco em modo somente leitura.",
        ) from exc
    try:
        connection.execute("PRAGMA query_only = ON").close()
        query_only_row = connection.execute("PRAGMA query_only").fetchone()
        if query_only_row is None or int(query_only_row[0]) != 1:
            raise GuardError(
                "read_only_failed",
                "Não foi possível ativar a proteção somente leitura.",
            )
        connection.execute("PRAGMA foreign_keys = ON").close()
        connection.execute("PRAGMA busy_timeout = 30000").close()
        return connection
    except Exception:
        connection.close()
        raise


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
    raise GuardError(
        "unsupported_database_value",
        "O banco contém um tipo de valor SQLite não suportado.",
    )


def _canonical_row(row: Sequence[object]) -> bytes:
    return json.dumps(
        [_canonical_sqlite_value(value) for value in row],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")


def _add_frame(digest: Any, label: str, payload: bytes) -> None:
    label_bytes = label.encode("utf-8")
    digest.update(len(label_bytes).to_bytes(8, "big"))
    digest.update(label_bytes)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _logical_fingerprint(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    digest.update(FINGERPRINT_DOMAIN)

    user_version_row = connection.execute("PRAGMA user_version").fetchone()
    user_version = int(user_version_row[0]) if user_version_row else 0
    _add_frame(digest, "user_version", str(user_version).encode("ascii"))

    schema_cursor = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema"
    )
    try:
        schema_rows = sorted(_canonical_row(tuple(row)) for row in schema_cursor)
    finally:
        schema_cursor.close()
    _add_frame(digest, "sqlite_schema.count", str(len(schema_rows)).encode("ascii"))
    for schema_row in schema_rows:
        _add_frame(digest, "sqlite_schema.row", schema_row)

    table_cursor = connection.execute(
        "SELECT name FROM sqlite_schema "
        "WHERE type = 'table' "
        "AND lower(substr(name, 1, 7)) <> 'sqlite_'"
    )
    try:
        table_names = {str(row[0]) for row in table_cursor}
    finally:
        table_cursor.close()
    sequence_row = connection.execute(
        "SELECT 1 FROM sqlite_schema "
        "WHERE type = 'table' AND name = 'sqlite_sequence'"
    ).fetchone()
    if sequence_row is not None:
        table_names.add("sqlite_sequence")

    _add_frame(digest, "tables.count", str(len(table_names)).encode("ascii"))
    for table_name in sorted(table_names):
        table_info_cursor = connection.execute(
            f"PRAGMA table_xinfo({_quote_identifier(table_name)})"
        )
        try:
            columns = [str(row[1]) for row in table_info_cursor]
        finally:
            table_info_cursor.close()
        if not columns:
            raise GuardError(
                "invalid_database",
                "Uma tabela do banco não possui uma definição legível.",
            )

        table_payload = json.dumps(
            {"columns": columns, "name": table_name},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        _add_frame(digest, "table", table_payload)

        selected_columns = ",".join(_quote_identifier(name) for name in columns)
        row_cursor = connection.execute(
            f"SELECT {selected_columns} FROM {_quote_identifier(table_name)}"
        )
        try:
            canonical_rows = sorted(_canonical_row(tuple(row)) for row in row_cursor)
        finally:
            row_cursor.close()
        _add_frame(
            digest,
            "table.rows.count",
            str(len(canonical_rows)).encode("ascii"),
        )
        for canonical_row in canonical_rows:
            _add_frame(digest, "table.row", canonical_row)

    return digest.hexdigest()


def _inspect_connection(connection: sqlite3.Connection) -> dict[str, Any]:
    quick_cursor = connection.execute("PRAGMA quick_check")
    try:
        quick_check = [str(row[0]) for row in quick_cursor]
    finally:
        quick_cursor.close()
    if quick_check != ["ok"]:
        raise GuardError(
            "quick_check_failed",
            "A verificação de integridade do banco falhou.",
        )

    foreign_key_cursor = connection.execute("PRAGMA foreign_key_check")
    try:
        foreign_key_violations = foreign_key_cursor.fetchall()
    finally:
        foreign_key_cursor.close()
    if foreign_key_violations:
        raise GuardError(
            "foreign_key_check_failed",
            "A verificação de chaves estrangeiras do banco falhou.",
        )

    return {
        "foreign_key_check": [],
        "logical_fingerprint": _logical_fingerprint(connection),
        "quick_check": quick_check,
    }


def _inspect_database(database_path: Path) -> dict[str, Any]:
    connection = _open_read_only(database_path)
    transaction_started = False
    try:
        connection.execute("BEGIN").close()
        transaction_started = True
        return _inspect_connection(connection)
    except GuardError:
        raise
    except sqlite3.Error as exc:
        raise GuardError(
            "invalid_database",
            "O arquivo configurado não é um banco SQLite válido.",
        ) from exc
    finally:
        if transaction_started:
            try:
                connection.execute("ROLLBACK").close()
            except sqlite3.Error:
                pass
        connection.close()


def _normalize_expected_fingerprint(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not FINGERPRINT_PATTERN.fullmatch(normalized):
        raise GuardError(
            "invalid_expected_fingerprint",
            "A impressão lógica esperada é inválida.",
            exit_code=2,
        )
    return normalized


def _path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _remove_partial_files(partial_path: Path) -> None:
    for candidate in (
        partial_path,
        Path(f"{partial_path}-journal"),
        Path(f"{partial_path}-wal"),
        Path(f"{partial_path}-shm"),
    ):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _backup_database(
    database_path: Path,
    destination_value: str | os.PathLike[str],
    expected_fingerprint_value: str | None,
    *,
    raw_config: dict[str, Any],
    expected_backup_root_value: str | os.PathLike[str] | None,
) -> dict[str, Any]:
    expected_fingerprint = _normalize_expected_fingerprint(
        expected_fingerprint_value
    )
    destination = _resolve_backup_destination(
        destination_value,
        raw_config=raw_config,
        expected_backup_root_value=expected_backup_root_value,
    )
    if _path_exists(destination):
        raise GuardError(
            "destination_exists",
            "O destino do backup já existe.",
        )

    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    partial_path: Path | None = None
    source_transaction_started = False
    source_report: dict[str, Any] | None = None
    try:
        source = _open_read_only(database_path)
        source.execute("BEGIN").close()
        source_transaction_started = True
        try:
            source_report = _inspect_connection(source)
        except sqlite3.Error as exc:
            raise GuardError(
                "invalid_database",
                "O arquivo configurado não é um banco SQLite válido.",
            ) from exc

        source_fingerprint = str(source_report["logical_fingerprint"])
        if (
            expected_fingerprint is not None
            and source_fingerprint != expected_fingerprint
        ):
            raise GuardError(
                "stale_fingerprint",
                "O banco mudou depois da impressão lógica esperada.",
            )

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GuardError(
                "destination_unavailable",
                "Não foi possível preparar o diretório do backup.",
            ) from exc
        if _path_exists(destination):
            raise GuardError(
                "destination_exists",
                "O destino do backup já existe.",
            )
        partial_path = destination.with_name(
            f".{destination.name}.{uuid4().hex}.partial"
        )

        try:
            target = sqlite3.connect(
                partial_path,
                timeout=30,
                isolation_level=None,
                cached_statements=0,
            )
            source.backup(target)
            journal_mode_row = target.execute("PRAGMA journal_mode = DELETE").fetchone()
            journal_mode = (
                str(journal_mode_row[0]).lower() if journal_mode_row else ""
            )
            if journal_mode != "delete":
                raise GuardError(
                    "journal_consolidation_failed",
                    "Não foi possível consolidar o backup em arquivo único.",
                )
        except GuardError:
            raise
        except sqlite3.Error as exc:
            raise GuardError(
                "backup_failed",
                "A API de backup do SQLite não concluiu a cópia.",
            ) from exc
        finally:
            if target is not None:
                target.close()
                target = None
            if source_transaction_started and source is not None:
                try:
                    source.execute("ROLLBACK").close()
                except sqlite3.Error:
                    pass
                source_transaction_started = False
            if source is not None:
                source.close()
                source = None

        partial_report = _inspect_database(partial_path)
        if partial_report["logical_fingerprint"] != source_fingerprint:
            raise GuardError(
                "backup_fingerprint_mismatch",
                "O backup não preservou a impressão lógica da origem.",
            )
        if any(
            _path_exists(Path(f"{partial_path}{suffix}"))
            for suffix in ("-journal", "-wal", "-shm")
        ):
            raise GuardError(
                "journal_consolidation_failed",
                "Não foi possível consolidar o backup em arquivo único.",
            )

        backup_bytes = partial_path.stat().st_size
        backup_sha256 = _file_sha256(partial_path)
        with partial_path.open("r+b") as partial_file:
            os.fsync(partial_file.fileno())

        if _path_exists(destination):
            raise GuardError(
                "destination_exists",
                "O destino do backup já existe.",
            )
        os.replace(partial_path, destination)
        partial_path = None

        return {
            "backup_bytes": backup_bytes,
            "backup_sha256": backup_sha256,
            "command": "backup",
            "destination": str(destination),
            "foreign_key_check": [],
            "fingerprint_format": FINGERPRINT_FORMAT,
            "format": OUTPUT_FORMAT,
            "journal_mode": "delete",
            "logical_fingerprint": source_fingerprint,
            "ok": True,
            "quick_check": "ok",
            "quick_check_rows": ["ok"],
            "sha256": backup_sha256,
        }
    except GuardError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise GuardError(
            "backup_failed",
            "O backup não pôde ser concluído.",
        ) from exc
    finally:
        if target is not None:
            target.close()
        if source_transaction_started and source is not None:
            try:
                source.execute("ROLLBACK").close()
            except sqlite3.Error:
                pass
        if source is not None:
            source.close()
        if partial_path is not None:
            _remove_partial_files(partial_path)


def _build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(
        description="Verifica, identifica e copia SQLite sem importar a aplicação.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--config-path", required=True)
    verify_parser.add_argument("--expected-database-path")

    fingerprint_parser = subparsers.add_parser("fingerprint")
    fingerprint_parser.add_argument("--config-path", required=True)
    fingerprint_parser.add_argument("--expected-database-path")

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--config-path", required=True)
    backup_parser.add_argument("--expected-database-path")
    backup_parser.add_argument("--expected-backup-root")
    backup_parser.add_argument("--destination", required=True)
    backup_parser.add_argument("--expected-fingerprint")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
        database_path, raw_config = _resolve_database_path(
            args.config_path,
            args.expected_database_path,
        )

        if args.command == "backup":
            result = _backup_database(
                database_path,
                args.destination,
                args.expected_fingerprint,
                raw_config=raw_config,
                expected_backup_root_value=args.expected_backup_root,
            )
        else:
            report = _inspect_database(database_path)
            result = {
                "command": args.command,
                "fingerprint_format": FINGERPRINT_FORMAT,
                "format": OUTPUT_FORMAT,
                "logical_fingerprint": report["logical_fingerprint"],
                "ok": True,
            }
            if args.command == "verify":
                result["foreign_key_check"] = report["foreign_key_check"]
                result["quick_check"] = "ok"
                result["quick_check_rows"] = report["quick_check"]
        _emit_json(result, sys.stdout)
        return 0
    except GuardError as exc:
        _emit_json(
            {
                "error": {"code": exc.code, "message": exc.message},
                "format": OUTPUT_FORMAT,
                "ok": False,
            },
            sys.stderr,
        )
        return exc.exit_code
    except (OSError, sqlite3.Error, ValueError):
        _emit_json(
            {
                "error": {
                    "code": "operation_failed",
                    "message": "A operação de proteção do banco falhou.",
                },
                "format": OUTPUT_FORMAT,
                "ok": False,
            },
            sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
