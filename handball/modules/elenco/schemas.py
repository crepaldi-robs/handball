from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# Cópia local dos schemas de membro (não importar entre módulos): as rotas
# antigas de presenças seguem como compatibilidade até serem removidas.
class MemberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    position: str = Field(min_length=1, max_length=40)
    attack_positions: list[Literal["GOL", "PE", "ME", "C", "MD", "PD", "PV"]] | None = Field(default=None, max_length=7)
    defensive_positions: list[Literal["M1", "M2", "M3", "AVANCADO"]] | None = Field(default=None, max_length=4)


class MemberUpdate(BaseModel):
    position: str = Field(min_length=1, max_length=40)
    active: bool
    attack_positions: list[Literal["GOL", "PE", "ME", "C", "MD", "PD", "PV"]] | None = Field(default=None, max_length=7)
    defensive_positions: list[Literal["M1", "M2", "M3", "AVANCADO"]] | None = Field(default=None, max_length=4)


class RankingSessionCreate(BaseModel):
    scope: Literal["LINE", "GOALKEEPER"]
    member_id: int = Field(gt=0)
    rerank: bool = False


class RankingAnswer(BaseModel):
    reference_member_id: int = Field(gt=0)
    outcome: Literal["BETTER", "WORSE", "EQUAL"]


class RefinementUpdate(BaseModel):
    position: Literal["GOL", "PE", "ME", "C", "MD", "PD", "PV"]
    member_ids: list[int] = Field(min_length=1, max_length=40)
