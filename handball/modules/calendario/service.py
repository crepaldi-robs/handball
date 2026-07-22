from __future__ import annotations

from .schemas import CalendarModuleStatus


class CalendarService:
    """Expõe apenas o estado do módulo, sem consultar persistência."""

    def status(self) -> CalendarModuleStatus:
        return CalendarModuleStatus()
