from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager import DatabaseManager
    from .repositories.attendance import AttendanceRepository


class UnitOfWork:
    """Uma conexão e uma fronteira transacional por operação de aplicação."""

    def __init__(self, manager: DatabaseManager, *, read_only: bool = False) -> None:
        self._manager = manager
        self._read_only = bool(read_only)
        self._connection: Any | None = None
        self._attendance: AttendanceRepository | None = None
        self._completed = False

    def __enter__(self) -> UnitOfWork:
        if self._connection is not None:
            raise RuntimeError("A unidade de trabalho já está ativa.")
        self._connection = (
            self._manager._adapter.connect_read_only()
            if self._read_only
            else self._manager._adapter.connect_write()
        )
        try:
            if not self._read_only:
                self._connection.execute("BEGIN").close()
        except Exception:
            self._connection.close()
            self._connection = None
            raise
        self._completed = False
        return self

    @property
    def connection(self) -> Any:
        if self._connection is None:
            raise RuntimeError("A unidade de trabalho não está ativa.")
        if self._completed:
            raise RuntimeError("A unidade de trabalho já foi concluída.")
        return self._connection

    @property
    def attendance(self) -> AttendanceRepository:
        if self._attendance is None:
            from .repositories.attendance import AttendanceRepository

            self._attendance = AttendanceRepository(
                self._manager,
                _connection=self.connection,
                _read_only=self._read_only,
            )
        return self._attendance

    def commit(self) -> None:
        if self._read_only:
            raise RuntimeError("Unidade de trabalho somente leitura não faz commit.")
        connection = self.connection
        connection.commit()
        self._completed = True

    def rollback(self) -> None:
        if self._read_only:
            raise RuntimeError("Unidade de trabalho somente leitura não faz rollback.")
        connection = self.connection
        connection.rollback()
        self._completed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        if self._connection is None:
            return False
        try:
            if self._read_only:
                self._completed = True
            elif not self._completed:
                if exc_type is None:
                    self._connection.commit()
                else:
                    self._connection.rollback()
                self._completed = True
        finally:
            self._attendance = None
            self._connection.close()
            self._connection = None
        return False


class UnitOfWorkFactory:
    """Factory injetável e callable usada pelos serviços dos módulos."""

    def __init__(self, manager: DatabaseManager) -> None:
        self._manager = manager

    def __call__(self, *, read_only: bool = False) -> UnitOfWork:
        return UnitOfWork(self._manager, read_only=read_only)
