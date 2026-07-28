"""Exploração SQLite: somente leitura por padrão; escrita completa (DML/DDL)
quando o chamador tem sql.admin, sempre preservando RESTRICTED_RELATIONS."""
from __future__ import annotations

import csv
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Iterator


RESTRICTED_RELATIONS = frozenset({"users", "auth_sessions", "schema_migrations"})

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
    "REINDEX", "RELEASE", "ROLLBACK", "SAVEPOINT", "VACUUM",
})

WRITE_LEADING_TOKENS = frozenset({"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"})

# Ações liberadas apenas com allow_write=True, e mesmo assim negadas se a
# tabela/índice alvo estiver em RESTRICTED_RELATIONS. O valor indica se o
# nome da tabela vem em arg1 ou arg2 do callback do authorizer do SQLite.
_TABLE_SCOPED_WRITE_ACTIONS: dict[int, int] = {
    sqlite3.SQLITE_INSERT: 1,
    sqlite3.SQLITE_UPDATE: 1,
    sqlite3.SQLITE_DELETE: 1,
    sqlite3.SQLITE_CREATE_TABLE: 1,
    sqlite3.SQLITE_DROP_TABLE: 1,
    sqlite3.SQLITE_CREATE_INDEX: 2,
    sqlite3.SQLITE_DROP_INDEX: 2,
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
                    "São permitidas consultas SELECT, WITH, EXPLAIN, INSERT, UPDATE, DELETE, CREATE, ALTER e DROP."
                )
            raise ValueError("São permitidas somente consultas SELECT, WITH e EXPLAIN.")
        if tokens[0] == "EXPLAIN" and not allow_explain:
            raise ValueError("EXPLAIN não é aceito nesta operação.")
        forbidden = FORBIDDEN_TOKENS_ADMIN if allow_write else FORBIDDEN_TOKENS_READONLY
        if any(token in forbidden for token in tokens):
            raise ValueError("A consulta contém um comando não permitido.")
        return tokens

    def _install_guard(self, *, allow_write: bool = False) -> None:
        def authorizer(action: int, arg1: str | None, arg2: str | None, database: str | None, source: str | None) -> int:
            del database, source
            if action in _ALWAYS_DENIED_ACTIONS:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ and (arg1 or "").casefold() in RESTRICTED_RELATIONS:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and (arg1 or "").casefold() == "load_extension":
                return sqlite3.SQLITE_DENY
            table_arg_position = _TABLE_SCOPED_WRITE_ACTIONS.get(action)
            if table_arg_position is not None:
                if not allow_write:
                    return sqlite3.SQLITE_DENY
                table_name = arg1 if table_arg_position == 1 else arg2
                if (table_name or "").casefold() in RESTRICTED_RELATIONS:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.connection.set_authorizer(authorizer)

    def _execute(self, sql: str, *, allow_write: bool = False) -> sqlite3.Cursor:
        self._install_guard(allow_write=allow_write)
        deadline = time.monotonic() + self.timeout_seconds
        self.connection.set_progress_handler(
            lambda: 1 if time.monotonic() >= deadline else 0,
            10_000,
        )
        try:
            return self.connection.execute(sql)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).casefold():
                raise TimeoutError("A consulta excedeu o tempo máximo de execução.") from exc
            raise ValueError(f"SQLite recusou a consulta: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"SQLite recusou a consulta: {exc}") from exc
        finally:
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
            return {
                "columns": [], "rows": [], "page": page, "page_size": page_size,
                "has_more": False,
                "affected_rows": affected if affected is not None and affected >= 0 else 0,
            }
        offset = (page - 1) * page_size
        if offset:
            cursor.fetchmany(offset)
        rows = [dict(row) for row in cursor.fetchmany(page_size + 1)]
        has_more = len(rows) > page_size
        return {"columns": columns, "rows": rows[:page_size], "page": page, "page_size": page_size, "has_more": has_more}

    def explain(self, sql: str) -> list[dict[str, Any]]:
        self._validate(sql, allow_explain=False)
        return [dict(row) for row in self._execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()]

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
            workbook.close()
        return Path(handle.name)
