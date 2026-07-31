from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from handball.core.calendar import (
    CalendarEventStatus,
    CalendarEventType,
    CollectiveRestrictionKind,
)


class CalendarEventInput(BaseModel):
    team_id: int = Field(gt=0)
    season_id: int = Field(gt=0)
    event_type: CalendarEventType
    status: CalendarEventStatus = CalendarEventStatus.PLANNED
    starts_at: datetime
    ends_at: datetime
    location: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=4000)
    title: str = Field(default="", max_length=180)
    opponent: str = Field(default="", max_length=180)
    all_day: bool = False
    is_countdown_target: bool = False
    version: int | None = Field(default=None, ge=1)
    restriction_kind: CollectiveRestrictionKind | None = None
    attendance_session_id: int | None = Field(default=None, gt=0)

    @field_validator("location", "notes", "title", "opponent")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_interval_and_relations(self) -> CalendarEventInput:
        if self.ends_at <= self.starts_at:
            raise ValueError("O fim do evento deve ocorrer depois do início.")
        if (
            self.event_type is CalendarEventType.COLLECTIVE_RESTRICTION
            and self.restriction_kind is None
        ):
            raise ValueError("A restrição coletiva exige um motivo formal.")
        if (
            self.event_type is not CalendarEventType.COLLECTIVE_RESTRICTION
            and self.restriction_kind is not None
        ):
            raise ValueError(
                "Motivo de restrição só se aplica a restrição coletiva."
            )
        if (
            self.attendance_session_id is not None
            and self.event_type is not CalendarEventType.TRAINING
        ):
            raise ValueError("Somente treino pode referenciar uma presença.")
        if self.opponent and self.event_type is not CalendarEventType.GAME:
            raise ValueError("Adversário só se aplica a jogos.")
        if (
            self.is_countdown_target
            and self.event_type is not CalendarEventType.CHAMPIONSHIP
        ):
            raise ValueError("O alvo da contagem deve ser um campeonato.")
        if (
            self.event_type is CalendarEventType.CANCELLATION_RESCHEDULING
            and self.status
            not in {CalendarEventStatus.CANCELLED, CalendarEventStatus.RESCHEDULED}
        ):
            raise ValueError(
                "Cancelamento/remarcação exige status CANCELLED ou RESCHEDULED."
            )
        return self


class CalendarActionInput(BaseModel):
    reason: str = Field(default="", max_length=1000)
    base_version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class CalendarRescheduleInput(CalendarActionInput):
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def validate_interval(self) -> CalendarRescheduleInput:
        if self.ends_at <= self.starts_at:
            raise ValueError("O novo fim deve ocorrer depois do novo início.")
        if not self.reason:
            raise ValueError("Informe por que o evento foi remarcado.")
        return self


class CalendarConflictCheckInput(BaseModel):
    team_id: int = Field(gt=0)
    starts_at: datetime
    ends_at: datetime
    event_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> CalendarConflictCheckInput:
        if self.ends_at <= self.starts_at:
            raise ValueError("O fim do evento deve ocorrer depois do início.")
        return self


class CalendarSeriesInput(BaseModel):
    team_id: int = Field(gt=0)
    season_id: int = Field(gt=0)
    event_type: CalendarEventType = CalendarEventType.TRAINING
    title: str = Field(default="", max_length=180)
    opponent: str = Field(default="", max_length=180)
    starts_on: date
    ends_on: date
    start_time: time
    duration_minutes: int = Field(default=120, gt=0, le=24 * 60)
    weekdays: list[int] = Field(min_length=1, max_length=7)
    location: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=4000)
    restriction_kind: CollectiveRestrictionKind | None = None

    @field_validator("title", "opponent", "location", "notes")
    @classmethod
    def strip_series_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, values: list[int]) -> list[int]:
        if any(value < 0 or value > 6 for value in values):
            raise ValueError("Dias da semana devem ficar entre 0 e 6.")
        return sorted(set(values))

    @model_validator(mode="after")
    def validate_series(self) -> CalendarSeriesInput:
        if self.ends_on < self.starts_on:
            raise ValueError("O fim da recorrência deve ser posterior ao início.")
        if (self.ends_on - self.starts_on).days > 370:
            raise ValueError("A série pode cobrir no máximo 370 dias.")
        if self.opponent and self.event_type is not CalendarEventType.GAME:
            raise ValueError("Adversário só se aplica a jogos.")
        if (
            self.event_type is CalendarEventType.COLLECTIVE_RESTRICTION
            and self.restriction_kind is None
        ):
            raise ValueError("A restrição coletiva exige um motivo formal.")
        if (
            self.event_type is not CalendarEventType.COLLECTIVE_RESTRICTION
            and self.restriction_kind is not None
        ):
            raise ValueError(
                "Motivo de restrição só se aplica a restrição coletiva."
            )
        return self


class CalendarSeriesEditInput(CalendarEventInput):
    scope: Literal["FUTURE", "ALL"]
    anchor_event_id: int = Field(gt=0)


class CalendarJustificationInput(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A justificativa não pode ficar vazia.")
        return value
