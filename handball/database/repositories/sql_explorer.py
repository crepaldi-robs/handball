"""Exploração SQLite com leitura isolada e alterações administrativas protegidas."""
from __future__ import annotations

import csv
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator

if TYPE_CHECKING:
    from handball.database.manager import DatabaseManager


RESTRICTED_RELATIONS = frozenset({"schema_migrations", "sqlite_sequence"})
IMMUTABLE_RELATIONS = frozenset({
    "attendance_audit_log", "security_audit_events", "schema_migrations",
    "sqlite_sequence",
})
STRUCTURE_PROTECTED_RELATIONS = frozenset({
    "users", "auth_sessions", "system_roles", "membership_roles",
    "player_user_links", "user_permission_grants",
    *IMMUTABLE_RELATIONS,
})
SECRET_COLUMNS = {
    "users": frozenset({"password_hash"}),
    "auth_sessions": frozenset({"token_hash", "csrf_token"}),
}

FORBIDDEN_TOKENS_READONLY = frozenset({
    "ALTER", "ANALYZE", "ATTACH", "BEGIN", "COMMIT", "CREATE", "DELETE",
    "DETACH", "DROP", "END", "INSERT", "PRAGMA", "REINDEX", "RELEASE",
    "ROLLBACK", "SAVEPOINT", "UPDATE", "VACUUM",
})

# Com allow_write=True (permissão sql.admin), DML/DDL sobre tabelas comuns
# passa a ser permitido; o que continua proibido é o que mexe no motor/arquivo
# ou sobrevive à requisição (trigger, view, tabela virtual, objeto temporário
# — ver _install_guard), além de controle de transação manual, que conflita
# com o BEGIN implícito da UnitOfWork.
FORBIDDEN_TOKENS_ADMIN = frozenset({
    "ANALYZE", "ATTACH", "BEGIN", "COMMIT", "DETACH", "END", "PRAGMA",
    "REINDEX", "RELEASE", "ROLLBACK", "SAVEPOINT", "VACUUM", "DROP",
    "RETURNING",
})

WRITE_LEADING_TOKENS = frozenset({"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"})

# Ações liberadas apenas com allow_write=True, e mesmo assim negadas se a
# tabela/índice alvo estiver em RESTRICTED_RELATIONS. O valor indica se o
# nome da tabela vem em arg1 ou arg2 do callback do authorizer do SQLite.
_TABLE_SCOPED_WRITE_ACTIONS: dict[int, int] = {
    sqlite3.SQLITE_INSERT: 1,
    sqlite3.SQLITE_UPDATE: 1,
    sqlite3.SQLITE_DELETE: 1,
    sqlite3.SQLITE_CREATE_TABLE: 1,
    sqlite3.SQLITE_CREATE_INDEX: 2,
    sqlite3.SQLITE_ALTER_TABLE: 2,
}

# Sempre negado, mesmo com allow_write=True: engine/arquivo (pragma, attach,
# vacuum...) e qualquer objeto que sobrevive à requisição e pode executar
# código fora do escopo desta conexão (trigger, view, tabela virtual, temp).
_ALWAYS_DENIED_ACTIONS = frozenset({
    sqlite3.SQLITE_CREATE_TEMP_INDEX, sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_TRIGGER, sqlite3.SQLITE_CREATE_TEMP_VIEW,
    sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_CREATE_VTABLE,
    sqlite3.SQLITE_DROP_TEMP_INDEX, sqlite3.SQLITE_DROP_TEMP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_TRIGGER, sqlite3.SQLITE_DROP_TEMP_VIEW,
    sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_DROP_VTABLE,
    sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_PRAGMA, sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT,
    sqlite3.SQLITE_REINDEX, sqlite3.SQLITE_ANALYZE,
})


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tokens(sql: str) -> list[str]:
    """Extrai palavras fora de literais e comentários; rejeita ponto e vírgula."""
    result: list[str] = []
    index = 0
    size = len(sql)
    while index < size:
        char = sql[index]
        if char.isspace():
            index += 1
        elif sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = size if newline < 0 else newline + 1
        elif sql.startswith("/*", index):
            closing = sql.find("*/", index + 2)
            if closing < 0:
                raise ValueError("Comentário SQL sem fechamento.")
            index = closing + 2
        elif char in "'\"`":
            quote = char
            index += 1
            while index < size:
                if sql[index] == quote:
                    if index + 1 < size and sql[index + 1] == quote:
                        index += 2
                    else:
                        index += 1
                        break
                else:
                    index += 1
            else:
                raise ValueError("Literal SQL sem fechamento.")
        elif char == "[":
            closing = sql.find("]", index + 1)
            if closing < 0:
                raise ValueError("Identificador SQL sem fechamento.")
            index = closing + 1
        elif char == ";":
            raise ValueError("Execute uma única instrução, sem ponto e vírgula.")
        elif char.isalpha() or char == "_":
            end = index + 1
            while end < size and (sql[end].isalnum() or sql[end] in "_$"):
                end += 1
            result.append(sql[index:end].upper())
            index = end
        else:
            index += 1
    return result


def _table_shapes(connection: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    names = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        name: tuple(
            str(row[1])
            for row in connection.execute(
                f"PRAGMA table_info({_identifier(name)})"
            )
        )
        for name in names
    }


def _row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        name: int(
            connection.execute(f"SELECT count(*) FROM {_identifier(name)}").fetchone()[0]
        )
        for name in _table_shapes(connection)
    }


def _index_shapes(
    connection: sqlite3.Connection,
) -> dict[str, tuple[str, bool, bool, str, tuple[str, ...]]]:
    result: dict[str, tuple[str, bool, bool, str, tuple[str, ...]]] = {}
    for table in _table_shapes(connection):
        for row in connection.execute(f"PRAGMA index_list({_identifier(table)})"):
            name = str(row["name"])
            columns = tuple(
                str(item["name"])
                for item in sorted(
                    connection.execute(f"PRAGMA index_info({_identifier(name)})"),
                    key=lambda item: int(item["seqno"]),
                )
            )
            result[name] = (
                table,
                bool(row["unique"]),
                bool(row["partial"]),
                str(row["origin"]),
                columns,
            )
    return result


def _require_safe_schema_change(
    before_tables: dict[str, tuple[str, ...]],
    after_tables: dict[str, tuple[str, ...]],
    before_indexes: dict[str, tuple[str, bool, bool, str, tuple[str, ...]]],
    after_indexes: dict[str, tuple[str, bool, bool, str, tuple[str, ...]]],
) -> list[str]:
    changes: list[str] = []
    for table, columns in before_tables.items():
        if table not in after_tables:
            raise ValueError("A alteração removeria uma tabela existente.")
        if after_tables[table][: len(columns)] != columns:
            raise ValueError(
                "ALTER só pode acrescentar colunas ao final; renomear, remover "
                "ou modificar colunas existentes foi bloqueado."
            )
        if after_tables[table] != columns:
            changes.append(table)
    for name, definition in before_indexes.items():
        if after_indexes.get(name) != definition:
            raise ValueError("A alteração modificaria um índice existente.")
    for name, definition in after_indexes.items():
        if name not in before_indexes:
            is_new_table_primary_key = (
                definition[3] == "pk" and definition[0] not in before_tables
            )
            if definition[1] and not is_new_table_primary_key:
                raise ValueError(
                    "CREATE UNIQUE INDEX e novas restrições UNIQUE foram bloqueados."
                )
            if not name.casefold().startswith("sqlite_"):
                changes.append(name)
    changes.extend(sorted(set(after_tables) - set(before_tables)))
    return sorted(set(changes))


def simulate_change(manager: DatabaseManager, sql: str) -> dict[str, Any]:
    """Executa a alteração em um clone volátil e devolve seu impacto."""
    simulation = sqlite3.connect(":memory:", isolation_level=None)
    simulation.row_factory = sqlite3.Row
    try:
        with manager.read_only_connection() as source:
            source.backup(simulation)
        simulation.execute("PRAGMA foreign_keys=ON")
        simulation.execute("BEGIN")
        before_shapes = _table_shapes(simulation)
        before_counts = _row_counts(simulation)
        result = SqlExplorerRepository(simulation).apply_change(sql)
        after_shapes = _table_shapes(simulation)
        after_counts = _row_counts(simulation)
        result["row_deltas"] = {
            table: after_counts.get(table, 0) - count
            for table, count in before_counts.items()
            if after_counts.get(table, 0) != count
        }
        result["cascade_rows"] = max(
            0,
            sum(abs(value) for value in result["row_deltas"].values())
            - int(result["affected_rows"]),
        )
        result["whole_table_warning"] = any(
            before_counts.get(table, 0) > 0 and after_counts.get(table, 0) == 0
            for table in result["tables"]
        )
        if [str(row[0]) for row in simulation.execute("PRAGMA quick_check")] != ["ok"]:
            raise ValueError("A alteração falhou na verificação de integridade.")
        if list(simulation.execute("PRAGMA foreign_key_check")):
            raise ValueError("A alteração criaria vínculos inválidos.")
        simulation.rollback()
        return result
    finally:
        simulation.close()


class SqlExplorerRepository:
    """Encapsula introspecção e execução, sem expor a conexão ao módulo web."""

    def __init__(self, connection: sqlite3.Connection, *, timeout_seconds: float = 5.0) -> None:
        self.connection = connection
        self.timeout_seconds = float(timeout_seconds)

    def _validate(self, sql: str, *, allow_explain: bool = True, allow_write: bool = False) -> list[str]:
        statement = sql.strip()
        if not statement:
            raise ValueError("Informe uma consulta SQL.")
        if len(statement) > 20_000:
            raise ValueError("A consulta excede o limite de 20.000 caracteres.")
        tokens = _tokens(statement)
        allowed_leading = {"SELECT", "WITH", "EXPLAIN"} | (WRITE_LEADING_TOKENS if allow_write else set())
        if not tokens or tokens[0] not in allowed_leading:
            if allow_write:
                raise ValueError(
                    "São permitidas alterações INSERT, UPDATE, DELETE, CREATE e ALTER."
                )
            raise ValueError("São permitidas somente consultas SELECT, WITH e EXPLAIN.")
        if tokens[0] == "EXPLAIN" and not allow_explain:
            raise ValueError("EXPLAIN não é aceito nesta operação.")
        forbidden = FORBIDDEN_TOKENS_ADMIN if allow_write else FORBIDDEN_TOKENS_READONLY
        if any(token in forbidden for token in tokens):
            raise ValueError("A consulta contém um comando não permitido.")
        if (
            allow_write
            and tokens[0] == "CREATE"
            and "UNIQUE" in tokens
            and "INDEX" in tokens
        ):
            raise ValueError("CREATE UNIQUE INDEX não é permitido.")
        return tokens

    def _install_guard(
        self, *, allow_write: bool = False, touched_tables: set[str] | None = None
    ) -> None:
        def authorizer(action: int, arg1: str | None, arg2: str | None, database: str | None, source: str | None) -> int:
            del database
            if action in _ALWAYS_DENIED_ACTIONS:
                return sqlite3.SQLITE_DENY
            table = (arg1 or "").casefold()
            column = (arg2 or "").casefold()
            if action == sqlite3.SQLITE_READ:
                if table in RESTRICTED_RELATIONS:
                    return sqlite3.SQLITE_DENY
                if column in SECRET_COLUMNS.get(table, ()):
                    return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or arg1 or "").casefold() == "load_extension":
                return sqlite3.SQLITE_DENY
            table_arg_position = _TABLE_SCOPED_WRITE_ACTIONS.get(action)
            if table_arg_position is not None:
                if not allow_write:
                    return sqlite3.SQLITE_DENY
                table_name = arg1 if table_arg_position == 1 else arg2
                normalized = (table_name or "").casefold()
                if normalized in IMMUTABLE_RELATIONS:
                    return sqlite3.SQLITE_DENY
                if action in {sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_ALTER_TABLE} and normalized in STRUCTURE_PROTECTED_RELATIONS:
                    return sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and normalized in {"users", "auth_sessions"}:
                    # O callback não informa as colunas de INSERT. Como essas
                    # tabelas exigem segredos, a única decisão segura é negar.
                    return sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_DELETE and normalized == "users":
                    return sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_UPDATE and column in SECRET_COLUMNS.get(normalized, ()):
                    return sqlite3.SQLITE_DENY
                if touched_tables is not None and normalized:
                    touched_tables.add(normalized)
            return sqlite3.SQLITE_OK

        self.connection.set_authorizer(authorizer)

    def _execute(
        self, sql: str, *, allow_write: bool = False,
        touched_tables: set[str] | None = None,
    ) -> sqlite3.Cursor:
        self._install_guard(allow_write=allow_write, touched_tables=touched_tables)
        deadline = time.monotonic() + self.timeout_seconds
        self.connection.set_progress_handler(
            lambda: 1 if time.monotonic() >= deadline else 0,
            10_000,
        )
        try:
            return self.connection.execute(sql)
        except sqlite3.OperationalError as exc:
            self._clear_guard()
            if "interrupted" in str(exc).casefold():
                raise TimeoutError("A consulta excedeu o tempo máximo de execução.") from exc
            raise ValueError("A consulta não pôde ser executada com segurança.") from exc
        except sqlite3.DatabaseError as exc:
            self._clear_guard()
            raise ValueError("A alteração violaria uma regra de integridade do banco.") from exc

    def _clear_guard(self) -> None:
        self.connection.set_progress_handler(None, 0)
        self.connection.set_authorizer(None)

    def catalog(self) -> dict[str, Any]:
        rows = self.connection.execute(
            """SELECT name,type,sql FROM sqlite_schema
               WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'
               ORDER BY type,name COLLATE NOCASE"""
        ).fetchall()
        relations: list[dict[str, Any]] = []
        for row in rows:
            name = str(row["name"])
            restricted = name.casefold() in RESTRICTED_RELATIONS
            relation: dict[str, Any] = {
                "name": name,
                "kind": str(row["type"]),
                "restricted": restricted,
                "columns": [],
                "primary_key": [],
                "foreign_keys": [],
                "indexes": [],
                "estimated_rows": None,
            }
            if not restricted:
                columns = self.connection.execute(
                    f"PRAGMA table_info({_identifier(name)})"
                ).fetchall()
                relation["columns"] = [
                    {"name": item["name"], "type": item["type"], "nullable": not bool(item["notnull"]), "default": item["dflt_value"], "primary_key_order": item["pk"]}
                    for item in columns
                ]
                relation["primary_key"] = [item["name"] for item in columns if item["pk"]]
                relation["foreign_keys"] = [dict(item) for item in self.connection.execute(f"PRAGMA foreign_key_list({_identifier(name)})").fetchall()]
                indexes = self.connection.execute(f"PRAGMA index_list({_identifier(name)})").fetchall()
                relation["indexes"] = [
                    {"name": item["name"], "unique": bool(item["unique"]), "columns": [column["name"] for column in self.connection.execute(f"PRAGMA index_info({_identifier(item['name'])})").fetchall()]}
                    for item in indexes
                ]
            relations.append(relation)
        return {"source": "operacional", "dialect": "sqlite", "relations": relations}

    def preview(self, sql: str, *, page: int, page_size: int, allow_write: bool = False) -> dict[str, Any]:
        self._validate(sql, allow_explain=False, allow_write=allow_write)
        if page < 1 or page_size < 1 or page_size > 200:
            raise ValueError("Página inválida; use página >= 1 e até 200 linhas.")
        cursor = self._execute(sql, allow_write=allow_write)
        columns = [item[0] for item in cursor.description or ()]
        if not columns:
            affected = cursor.rowcount
            result = {
                "columns": [], "rows": [], "page": page, "page_size": page_size,
                "has_more": False,
                "affected_rows": affected if affected is not None and affected >= 0 else 0,
            }
            self._clear_guard()
            return result
        offset = (page - 1) * page_size
        if offset:
            cursor.fetchmany(offset)
        rows = [dict(row) for row in cursor.fetchmany(page_size + 1)]
        self._clear_guard()
        has_more = len(rows) > page_size
        return {"columns": columns, "rows": rows[:page_size], "page": page, "page_size": page_size, "has_more": has_more}

    def explain(self, sql: str) -> list[dict[str, Any]]:
        self._validate(sql, allow_explain=False)
        cursor = self._execute(f"EXPLAIN QUERY PLAN {sql}")
        result = [dict(row) for row in cursor.fetchall()]
        self._clear_guard()
        return result

    def apply_change(self, sql: str) -> dict[str, Any]:
        tokens = self._validate(sql, allow_explain=False, allow_write=True)
        if tokens[0] in {"SELECT", "WITH", "EXPLAIN"}:
            raise ValueError("Use o endpoint de consulta para operações de leitura.")
        before_tables = _table_shapes(self.connection)
        before_indexes = _index_shapes(self.connection)
        touched: set[str] = set()
        cursor = self._execute(sql, allow_write=True, touched_tables=touched)
        try:
            if cursor.description:
                raise ValueError("Alterações com retorno de dados não são permitidas.")
            affected = cursor.rowcount if cursor.rowcount >= 0 else 0
        finally:
            self._clear_guard()
        after_tables = _table_shapes(self.connection)
        after_indexes = _index_shapes(self.connection)
        schema_changes = _require_safe_schema_change(
            before_tables, after_tables, before_indexes, after_indexes
        )
        quick = [str(row[0]) for row in self.connection.execute("PRAGMA quick_check")]
        foreign_keys = list(self.connection.execute("PRAGMA foreign_key_check"))
        if quick != ["ok"] or foreign_keys:
            raise ValueError("A alteração falhou na verificação de integridade.")
        return {
            "operation": tokens[0],
            "tables": sorted(
                table for table in touched
                if not table.casefold().startswith("sqlite_")
            ),
            "affected_rows": affected,
            "schema_changes": schema_changes,
        }

    def export_csv(self, sql: str) -> Path:
        self._validate(sql, allow_explain=False)
        cursor = self._execute(sql)
        handle = tempfile.NamedTemporaryFile(prefix="handball-sql-", suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8-sig")
        try:
            writer = csv.writer(handle)
            writer.writerow([item[0] for item in cursor.description or ()])
            while rows := cursor.fetchmany(1_000):
                writer.writerows(tuple(row) for row in rows)
        finally:
            self._clear_guard()
            handle.close()
        return Path(handle.name)

    def export_xlsx(self, sql: str) -> Path:
        self._validate(sql, allow_explain=False)
        try:
            import xlsxwriter
        except ImportError as exc:
            raise RuntimeError("Exportação Excel indisponível nesta instalação.") from exc
        cursor = self._execute(sql)
        handle = tempfile.NamedTemporaryFile(prefix="handball-sql-", suffix=".xlsx", delete=False)
        handle.close()
        workbook = xlsxwriter.Workbook(handle.name, {"constant_memory": True})
        try:
            worksheet = workbook.add_worksheet("Consulta")
            headers = [item[0] for item in cursor.description or ()]
            for column, value in enumerate(headers):
                worksheet.write(0, column, value)
            for row_number, row in enumerate(cursor, start=1):
                for column, value in enumerate(row):
                    worksheet.write(row_number, column, value)
        finally:
            self._clear_guard()
            workbook.close()
        return Path(handle.name)
