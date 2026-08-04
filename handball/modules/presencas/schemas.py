from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SyncOperation(BaseModel):
    operation_id: str = Field(min_length=8, max_length=100)
    member_id: int = Field(gt=0)
    base_version: int = Field(ge=1)
    confirmation_status: str
    present: bool | None = None
    notes: str = Field(default="", max_length=1000)
    creator_user_id: int | None = Field(default=None, ge=1)


class SyncBatch(BaseModel):
    operations: list[SyncOperation] = Field(min_length=1, max_length=100)
    offline: bool = False


class SessionNotes(BaseModel):
    notes: str = Field(default="", max_length=4000)


class SelfConfirmationInput(BaseModel):
    response: str = Field(pattern="^(GOING|NOT_GOING)$")
    positions: list[str] = Field(default_factory=list, max_length=12)
    justification: str = Field(default="", max_length=1000)
    base_version: int = Field(ge=1)


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
