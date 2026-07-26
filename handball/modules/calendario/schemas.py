from __future__ import annotations

from datetime import datetime

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
    restriction_kind: CollectiveRestrictionKind | None = None
    attendance_session_id: int | None = Field(default=None, gt=0)

    @field_validator("location", "notes")
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
        if (
            self.event_type is CalendarEventType.CANCELLATION_RESCHEDULING
            and self.status
            not in {CalendarEventStatus.CANCELLED, CalendarEventStatus.RESCHEDULED}
        ):
            raise ValueError(
                "Cancelamento/remarcação exige status CANCELLED ou RESCHEDULED."
            )
        return self


class CalendarJustificationInput(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A justificativa não pode ficar vazia.")
        return value
