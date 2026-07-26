from __future__ import annotations

from pathlib import Path
from typing import Any

from handball.core.authorization import AccessContext, Permission
from handball.database.contracts import UnitOfWorkFactoryContract


class SqlExplorerService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactoryContract) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    @staticmethod
    def _require(context: AccessContext) -> None:
        if context.must_change_password or Permission.SQL_EXPLORE not in context.permissions:
            raise PermissionError("Operação não autorizada.")

    def catalog(self, context: AccessContext) -> dict[str, Any]:
        self._require(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.sql_explorer.catalog()

    def preview(self, context: AccessContext, *, sql: str, page: int, page_size: int) -> dict[str, Any]:
        self._require(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.sql_explorer.preview(sql, page=page, page_size=page_size)

    def explain(self, context: AccessContext, *, sql: str) -> list[dict[str, Any]]:
        self._require(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.sql_explorer.explain(sql)

    def export(self, context: AccessContext, *, sql: str, format: str) -> Path:
        self._require(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            if format == "csv":
                return unit_of_work.sql_explorer.export_csv(sql)
            if format == "xlsx":
                return unit_of_work.sql_explorer.export_xlsx(sql)
        raise ValueError("Formato de exportação inválido.")
