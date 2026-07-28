from __future__ import annotations

from pathlib import Path
from typing import Any

from handball.core.authorization import AccessContext, Permission
from handball.database.contracts import UnitOfWorkFactoryContract


class SqlExplorerService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactoryContract) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    @staticmethod
    def _access(context: AccessContext) -> bool:
        """Valida a permissão e informa se o acesso é total (leitura e escrita)."""
        if context.must_change_password:
            raise PermissionError("Operação não autorizada.")
        if Permission.SQL_ADMIN in context.permissions:
            return True
        if Permission.SQL_EXPLORE in context.permissions:
            return False
        raise PermissionError("Operação não autorizada.")

    def catalog(self, context: AccessContext) -> dict[str, Any]:
        self._access(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.sql_explorer.catalog()

    def preview(self, context: AccessContext, *, sql: str, page: int, page_size: int) -> dict[str, Any]:
        allow_write = self._access(context)
        with self._unit_of_work_factory(read_only=not allow_write) as unit_of_work:
            return unit_of_work.sql_explorer.preview(sql, page=page, page_size=page_size, allow_write=allow_write)

    def explain(self, context: AccessContext, *, sql: str) -> list[dict[str, Any]]:
        self._access(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.sql_explorer.explain(sql)

    def export(self, context: AccessContext, *, sql: str, format: str) -> Path:
        self._access(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            if format == "csv":
                return unit_of_work.sql_explorer.export_csv(sql)
            if format == "xlsx":
                return unit_of_work.sql_explorer.export_xlsx(sql)
        raise ValueError("Formato de exportação inválido.")
