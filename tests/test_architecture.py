from __future__ import annotations

import ast
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "handball"
MODULES_ROOT = PACKAGE_ROOT / "modules"
DATABASE_ROOT = PACKAGE_ROOT / "database"

SQL_PATTERN = re.compile(
    r"\b(?:SELECT\s+.+?\s+FROM|INSERT\s+INTO|UPDATE\s+.+?\s+SET|"
    r"DELETE\s+FROM|CREATE\s+(?:TABLE|INDEX)|ALTER\s+TABLE|DROP\s+"
    r"(?:TABLE|INDEX)|PRAGMA)\b",
    flags=re.IGNORECASE | re.DOTALL,
)


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _string_constants(tree: ast.Module) -> list[str]:
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_modules_do_not_know_sqlite_sql_or_database_paths() -> None:
    for path in _python_files(MODULES_ROOT):
        tree = _tree(path)
        imports = _imported_names(tree)
        assert "sqlite3" not in imports, path
        assert not any(name.endswith("database.adapters.sqlite") for name in imports), path
        for value in _string_constants(tree):
            assert not SQL_PATTERN.search(value), f"SQL em {path}: {value[:80]!r}"
            assert ".db" not in value.lower(), f"Caminho de banco em {path}: {value!r}"


def test_sqlite_and_sql_are_restricted_to_database_package() -> None:
    for path in _python_files(PACKAGE_ROOT):
        if path.is_relative_to(DATABASE_ROOT):
            continue
        tree = _tree(path)
        assert "sqlite3" not in _imported_names(tree), path
        for value in _string_constants(tree):
            assert not SQL_PATTERN.search(value), f"SQL fora de database em {path}"


def test_database_package_does_not_depend_on_modules_or_interface() -> None:
    forbidden_prefixes = (
        "handball.modules",
        "fastapi",
        "jinja2",
    )
    for path in _python_files(DATABASE_ROOT):
        imports = _imported_names(_tree(path))
        assert not any(
            name == prefix or name.startswith(prefix + ".")
            for name in imports
            for prefix in forbidden_prefixes
        ), path


def test_internal_handball_import_graph_has_no_cycles() -> None:
    graph: dict[str, set[str]] = {}
    for path in _python_files(PACKAGE_ROOT):
        relative = path.relative_to(PROJECT_ROOT).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join(parts)
        graph[module] = {
            name
            for name in _imported_names(_tree(path))
            if name == "handball" or name.startswith("handball.")
        }

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str, trail: tuple[str, ...]) -> None:
        if module in visiting:
            raise AssertionError("Dependência circular: " + " -> ".join((*trail, module)))
        if module in visited or module not in graph:
            return
        visiting.add(module)
        for dependency in graph[module]:
            visit(dependency, (*trail, module))
        visiting.remove(module)
        visited.add(module)

    for module in graph:
        visit(module, ())


def test_entrypoint_is_minimal_and_uses_composition_root() -> None:
    path = PROJECT_ROOT / "app.py"
    tree = _tree(path)
    assert len(tree.body) == 2
    import_node, assignment = tree.body
    assert isinstance(import_node, ast.ImportFrom)
    assert import_node.module == "handball.application"
    assert [alias.name for alias in import_node.names] == ["create_app"]
    assert isinstance(assignment, ast.Assign)
    assert isinstance(assignment.value, ast.Call)
    assert isinstance(assignment.value.func, ast.Name)
    assert assignment.value.func.id == "create_app"


def test_schema_v1_identity_is_unchanged() -> None:
    from handball.database.migrations import (
        FINGERPRINT_FORMAT,
        LATEST_SCHEMA_VERSION,
        MIGRATION_V1_CHECKSUM,
    )

    assert LATEST_SCHEMA_VERSION == 3
    assert FINGERPRINT_FORMAT == "crepaldi-handball-logical-sqlite/v1"
    assert MIGRATION_V1_CHECKSUM == (
        "0369209bf3d35a2b752f2041a050c268"
        "61946bd6b3599831a398d5af6f5da821"
    )


def test_legacy_attendance_package_contains_no_persistence_implementation() -> None:
    legacy_root = PROJECT_ROOT / "attendance"
    for path in _python_files(legacy_root):
        tree = _tree(path)
        assert "sqlite3" not in _imported_names(tree), path
        for value in _string_constants(tree):
            assert not SQL_PATTERN.search(value), f"SQL legado em {path}"


def test_legacy_migrations_facade_does_not_reexport_persistence_internals() -> None:
    import attendance.migrations as legacy_migrations

    assert not hasattr(legacy_migrations, "sqlite3")
    assert not hasattr(legacy_migrations, "SCHEMA_V1_STATEMENTS")


def test_module_backup_contract_does_not_expose_physical_paths() -> None:
    from handball.database.contracts import BackupProvider

    assert "create_backup_download" in BackupProvider.__protocol_attrs__
    assert "create_backup" not in BackupProvider.__protocol_attrs__
