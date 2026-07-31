from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


class FolderCreateInput(BaseModel):
    team_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=160)
    parent_id: int | None = Field(default=None, gt=0)
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class FolderRenameInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class FolderMoveInput(BaseModel):
    parent_id: int | None = Field(default=None, gt=0)
    sort_order: int | None = Field(default=None, ge=0)


class FolderCopyInput(BaseModel):
    parent_id: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class FolderReorderInput(BaseModel):
    parent_id: int | None = Field(default=None, gt=0)
    folder_ids: list[int] = Field(min_length=1, max_length=300)


class PermanentDeleteInput(BaseModel):
    confirmation: str = Field(min_length=1, max_length=120)

    @field_validator("confirmation")
    @classmethod
    def strip_confirmation(cls, value: str) -> str:
        return value.strip()


class ContentPlacementInput(BaseModel):
    folder_id: int = Field(gt=0)
    placement_kind: Literal["PLACEMENT", "SHORTCUT"] = "PLACEMENT"
    sort_order: int = Field(default=0, ge=0)


class ContentInput(BaseModel):
    team_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=220)
    content_kind: str = Field(default="CONTENT", max_length=80)
    perspective: Literal["ATTACK", "DEFENSE", "NEUTRAL"] | None = None
    objective: str = Field(default="", max_length=4000)
    when_to_use: str = Field(default="", max_length=4000)
    prerequisites: str = Field(default="", max_length=4000)
    steps: str = Field(default="", max_length=24000)
    notes: str = Field(default="", max_length=8000)
    aliases: list[str] = Field(default_factory=list, max_length=80)
    positions: list[str] = Field(default_factory=list, max_length=40)
    placements: list[ContentPlacementInput] = Field(min_length=1, max_length=100)
    change_note: str = Field(default="", max_length=500)

    @field_validator(
        "title",
        "content_kind",
        "objective",
        "when_to_use",
        "prerequisites",
        "steps",
        "notes",
        "change_note",
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("aliases", "positions")
    @classmethod
    def normalize_list(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if any(len(value) > 120 for value in normalized):
            raise ValueError("Cada nome alternativo ou posição pode ter no máximo 120 caracteres.")
        return normalized


class ContentUpdateInput(ContentInput):
    team_id: int | None = Field(default=None, gt=0)


class ContentMoveInput(BaseModel):
    content_ids: list[int] = Field(min_length=1, max_length=100)
    folder_id: int = Field(gt=0)
    operation: Literal["MOVE", "SHORTCUT"] = "MOVE"

    @field_validator("content_ids")
    @classmethod
    def unique_content_ids(cls, values: list[int]) -> list[int]:
        if len(values) != len(set(values)):
            raise ValueError("Não repita um conteúdo na mesma operação.")
        return values


class ContentRelationInput(BaseModel):
    target_content_id: int = Field(gt=0)
    relation_type: Literal["PROPOSAL", "RESPONSE", "COUNTERRESPONSE", "VARIATION"]


class ContentRelationsInput(BaseModel):
    relations: list[ContentRelationInput] = Field(default_factory=list, max_length=100)


class DriveAttachmentInput(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    label: str = Field(default="", max_length=200)
    offline_essential: bool = False

    @field_validator("url")
    @classmethod
    def require_drive_https_url(cls, value: str) -> str:
        clean = value.strip()
        parsed = urlparse(clean)
        if parsed.scheme != "https" or parsed.hostname not in {
            "drive.google.com",
            "docs.google.com",
        }:
            raise ValueError("Informe um link HTTPS compartilhável do Google Drive ou Google Docs.")
        return clean

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str) -> str:
        return value.strip()


class PlanItemInput(BaseModel):
    content_id: int = Field(gt=0)
    sort_order: int = Field(default=0, ge=0)
    planned_minutes: int | None = Field(default=None, gt=0, le=600)
    notes: str = Field(default="", max_length=2000)

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: str) -> str:
        return value.strip()


class TrainingPlanInput(BaseModel):
    title: str = Field(default="", max_length=180)
    seasonal_objective: str = Field(default="", max_length=2000)
    context_adjustment: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=4000)
    items: list[PlanItemInput] = Field(default_factory=list, max_length=100)

    @field_validator("title", "seasonal_objective", "context_adjustment", "notes")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class PlanReuseInput(BaseModel):
    source_event_id: int = Field(gt=0)


class PlanEvaluationInput(BaseModel):
    content_id: int = Field(gt=0)
    mastery_stage: Literal["STARTING", "IMPROVING", "REFINING", "CONSOLIDATED"]
    continuity_decision: Literal["CONTINUE", "COMPLETE", "REVIEW"]
    notes: str = Field(default="", max_length=2000)

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: str) -> str:
        return value.strip()


class GuidedFinishInput(BaseModel):
    session_notes: str = Field(default="", max_length=4000)
    finalize_attendance: bool = True
    evaluations: list[PlanEvaluationInput] = Field(default_factory=list, max_length=100)

    @field_validator("session_notes")
    @classmethod
    def strip_notes(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def prevent_duplicate_evaluations(self) -> "GuidedFinishInput":
        ids = [item.content_id for item in self.evaluations]
        if len(ids) != len(set(ids)):
            raise ValueError("Cada conteúdo pode receber uma única avaliação final.")
        return self
