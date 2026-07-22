from __future__ import annotations

from .schemas import StatisticsModuleStatus


class StatisticsService:
    """Expõe apenas o estado do módulo, sem consultar persistência."""

    def status(self) -> StatisticsModuleStatus:
        return StatisticsModuleStatus()
