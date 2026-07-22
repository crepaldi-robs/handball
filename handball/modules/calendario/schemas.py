from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CalendarModuleStatus(BaseModel):
    key: Literal["calendario"] = "calendario"
    title: str = "Calendário"
    state: Literal["preparing"] = "preparing"
    state_label: str = "Em preparação"
    description: str = (
        "A organização de treinos e jogos será disponibilizada aqui em uma etapa futura."
    )
