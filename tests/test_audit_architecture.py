"""Garante mecanicamente a regra 4 do AGENTS.md: toda mudança em
confirmação/presença/observação gera auditoria.

Em vez de depender de alguém lembrar de testar cada novo caminho de escrita,
este módulo varre `handball/database` via AST e falha se alguma função
alterar `confirmation_status`/`present`/`notes` de `attendance_records` sem
também gravar em `attendance_audit_log` na mesma função.

Limitação conhecida e intencional: a checagem é por função, sem resolução de
chamada indireta. Se um refactor futuro mover o `INSERT INTO
attendance_audit_log` para um helper privado chamado a partir da função que
faz o `UPDATE`, este teste vai falhar mesmo que o comportamento continue
correto — a fricção é proposital: força revisão humana explícita da regra 4
em vez de deixar um falso-negativo passar em silêncio.
"""
from __future__ import annotations

import ast
import re
import textwrap

from tests.test_architecture import (
    DATABASE_ROOT,
    PROJECT_ROOT,
    _python_files,
    _string_constants,
    _tree,
)

AUDITED_COLUMNS = ("confirmation_status", "present", "notes")

ATTENDANCE_RECORDS_UPDATE = re.compile(r"UPDATE\s+attendance_records\b", re.IGNORECASE)
AUDIT_LOG_INSERT = re.compile(r"INSERT\s+INTO\s+attendance_audit_log\b", re.IGNORECASE)


def _set_clause(sql: str, match: re.Match[str]) -> str:
    rest = sql[match.end():]
    where = re.search(r"\bWHERE\b", rest, re.IGNORECASE)
    return rest[: where.start()] if where else rest


def _touches_audited_column(sql: str) -> bool:
    match = ATTENDANCE_RECORDS_UPDATE.search(sql)
    if not match:
        return False
    clause = _set_clause(sql, match)
    return any(re.search(rf"\b{column}\s*=", clause, re.IGNORECASE) for column in AUDITED_COLUMNS)


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def test_every_attendance_records_mutation_of_audited_columns_writes_attendance_audit_log() -> None:
    violations: list[str] = []
    for path in _python_files(DATABASE_ROOT):
        tree = _tree(path)
        for func in _functions(tree):
            constants = _string_constants(func)
            if not any(_touches_audited_column(sql) for sql in constants):
                continue
            if not any(AUDIT_LOG_INSERT.search(sql) for sql in constants):
                violations.append(f"{path.relative_to(PROJECT_ROOT)}:{func.name}")
    assert not violations, (
        "Função(ões) alteram confirmation_status/present/notes em "
        "attendance_records sem gravar em attendance_audit_log na mesma "
        "função (AGENTS.md regra 4): " + ", ".join(violations)
    )


def test_audit_architecture_scan_finds_the_known_write_paths() -> None:
    path = DATABASE_ROOT / "repositories" / "attendance.py"
    tree = _tree(path)
    flagged = {
        func.name
        for func in _functions(tree)
        if any(_touches_audited_column(sql) for sql in _string_constants(func))
    }
    assert {
        "update_self_confirmation",
        "save_records",
        "sync_records",
        "finalize_session",
    } <= flagged


def test_audit_detector_flags_synthetic_violation_and_ignores_session_notes_pattern() -> None:
    violating = ast.parse(
        textwrap.dedent(
            """
            def bad_update(conn, session_id, member_id, status, record_id):
                conn.execute(
                    "UPDATE attendance_records SET confirmation_status=?,version=version+1 WHERE id=?",
                    (status, record_id),
                )
            """
        )
    ).body[0]
    safe = ast.parse(
        textwrap.dedent(
            """
            def update_session_notes(conn, session_id, notes, now):
                conn.execute(
                    "UPDATE training_sessions SET notes = ?, updated_at = ? WHERE id = ?",
                    (notes, now, session_id),
                )
            """
        )
    ).body[0]

    assert any(_touches_audited_column(sql) for sql in _string_constants(violating))
    assert not any(AUDIT_LOG_INSERT.search(sql) for sql in _string_constants(violating))

    assert not any(_touches_audited_column(sql) for sql in _string_constants(safe))
