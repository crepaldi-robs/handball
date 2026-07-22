from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class StatisticsModuleStatus(BaseModel):
    key: Literal["estatisticas"] = "estatisticas"
    title: str = "Estatísticas"
    state: Literal["preparing"] = "preparing"
    state_label: str = "Em preparação"
    description: str = (
        "Indicadores esportivos serão disponibilizados aqui em uma etapa futura."
    )
