from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
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


class FolderTemplateNodeInput(BaseModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    parent_key: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    sort_order: int = Field(default=0, ge=0, le=1000)

    @field_validator("name")
    @classmethod
    def strip_template_name(cls, value: str) -> str:
        return value.strip()


class FolderTemplateApplyInput(BaseModel):
    team_id: int = Field(gt=0)
    nodes: list[FolderTemplateNodeInput] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_template_graph(self) -> "FolderTemplateApplyInput":
        keys = [node.key for node in self.nodes]
        if len(set(keys)) != len(keys):
            raise ValueError("A estrutura contém cartões duplicados.")
        known = set(keys)
        if any(node.parent_key is not None and node.parent_key not in known for node in self.nodes):
            raise ValueError("A estrutura contém uma pasta pai que não existe.")
        return self


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


class ContentPlacementsInput(BaseModel):
    placements: list[ContentPlacementInput] = Field(min_length=1, max_length=300)


class ExerciseRoleInput(BaseModel):
    group: Literal["ATTACK", "DEFENSE", "GOALKEEPER", "NEUTRAL"]
    label: str = Field(min_length=1, max_length=120)
    count: int = Field(default=1, ge=1, le=20)
    attack_positions: list[Literal["GOL", "PE", "ME", "C", "MD", "PD", "PV"]] = Field(default_factory=list, max_length=7)
    defensive_positions: list[Literal["M1", "M2", "M3", "AVANCADO"]] = Field(default_factory=list, max_length=4)
    allow_generic_defender: bool = False

    @field_validator("label")
    @classmethod
    def strip_role_label(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_role_positions(self) -> "ExerciseRoleInput":
        if self.group == "GOALKEEPER" and self.attack_positions not in ([], ["GOL"]):
            raise ValueError("O papel de goleiro só aceita a posição GOL.")
        if self.group == "DEFENSE" and self.attack_positions:
            raise ValueError("Um papel defensivo não deve exigir posição ofensiva.")
        if self.group == "ATTACK" and self.defensive_positions:
            raise ValueError("Um papel ofensivo não deve exigir marcador defensivo.")
        return self


class ExerciseVariantInput(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    roles: list[ExerciseRoleInput] = Field(min_length=1, max_length=40)

    @field_validator("label")
    @classmethod
    def strip_variant_label(cls, value: str) -> str:
        return value.strip()


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
    exercise_variants: list[ExerciseVariantInput] = Field(default_factory=list, max_length=20)
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

    @model_validator(mode="after")
    def validate_exercise_spec(self) -> "ContentInput":
        is_exercise = self.content_kind.strip().upper() == "EXERCISE"
        if self.exercise_variants and not is_exercise:
            raise ValueError("Requisitos de participantes só podem ser usados em conteúdo do tipo EXERCISE.")
        return self


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


class TodayItemInput(BaseModel):
    """Item do botão "Exercícios de hoje" na chamada.

    ``collective`` dispensa escolher conteúdo: o servidor usa (ou cria uma vez)
    o conteúdo "Coletivo" da equipe.
    """

    content_id: int | None = Field(default=None, gt=0)
    collective: bool = False
    planned_minutes: int | None = Field(default=None, gt=0, le=600)
    notes: str = Field(default="", max_length=2000)

    @field_validator("notes")
    @classmethod
    def strip_today_notes(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def exactly_one_source(self) -> "TodayItemInput":
        if self.collective == (self.content_id is not None):
            raise ValueError("Cada item é um conteúdo do Playbook ou o coletivo.")
        return self


class TodayPlanInput(BaseModel):
    items: list[TodayItemInput] = Field(default_factory=list, max_length=40)


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


class IndependentPlanInput(TrainingPlanInput):
    team_id: int = Field(gt=0)
    change_summary: str = Field(default="", max_length=500)

    @field_validator("change_summary")
    @classmethod
    def strip_change_summary(cls, value: str) -> str:
        return value.strip()


class PlaybookSeriesInput(BaseModel):
    team_id: int = Field(gt=0)
    plan_id: int | None = Field(default=None, gt=0)
    title: str = Field(default="", max_length=180)
    recurrence_rule: str = Field(default="", max_length=500)
    starts_on: str | None = Field(default=None, max_length=32)
    ends_on: str | None = Field(default=None, max_length=32)
    notes: str = Field(default="", max_length=4000)
    status: Literal["ACTIVE", "ARCHIVED"] = "ACTIVE"

    @field_validator("title", "recurrence_rule", "notes")
    @classmethod
    def strip_series_text(cls, value: str) -> str:
        return value.strip()


class PlaybookSessionInput(BaseModel):
    team_id: int | None = Field(default=None, gt=0)
    plan_id: int | None = Field(default=None, gt=0)
    series_id: int | None = Field(default=None, gt=0)
    title_override: str = Field(default="", max_length=180)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    local_overrides: dict[str, Any] = Field(default_factory=dict)
    execution_notes: str = Field(default="", max_length=4000)
    change_summary: str = Field(default="", max_length=500)

    @field_validator("title_override", "execution_notes", "change_summary")
    @classmethod
    def strip_session_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_interval(self) -> "PlaybookSessionInput":
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("O fim da sessão deve ocorrer depois do início.")
        return self


class SessionEventLinkInput(BaseModel):
    event_id: int = Field(gt=0)
    reason: str = Field(default="", max_length=1000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class SessionUnlinkInput(BaseModel):
    reason: str = Field(default="", max_length=1000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class SessionExecutionInput(BaseModel):
    execution_status: Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETED", "CANCELLED"] = "COMPLETED"
    execution_notes: str = Field(default="", max_length=4000)
    change_summary: str = Field(default="", max_length=500)

    @field_validator("execution_notes", "change_summary")
    @classmethod
    def strip_execution_text(cls, value: str) -> str:
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


class SessionEvaluationInput(BaseModel):
    """Avaliação de uma sessão, mesmo que ela ainda não tenha evento ligado."""

    calendar_event_id: int | None = Field(default=None, gt=0)
    evaluations: list[PlanEvaluationInput] = Field(default_factory=list, max_length=100)
    change_summary: str = Field(default="", max_length=500)

    @field_validator("change_summary")
    @classmethod
    def strip_change_summary(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def prevent_duplicate_evaluations(self) -> "SessionEvaluationInput":
        ids = [item.content_id for item in self.evaluations]
        if len(ids) != len(set(ids)):
            raise ValueError("Cada conteúdo pode receber uma única avaliação por sessão.")
        return self


class CompositionBlockInput(BaseModel):
    """Um bloco da prancheta (ex.: um exercício ou um monte do coletivo)."""

    block_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=120)
    roles: list[ExerciseRoleInput] = Field(min_length=1, max_length=40)

    @field_validator("label")
    @classmethod
    def strip_block_label(cls, value: str) -> str:
        return value.strip()


class CompositionAssignmentInput(BaseModel):
    """Ocupação manual de um slot, decidida pela CT — nunca sugerida aqui."""

    slot_id: str = Field(min_length=1, max_length=160)
    member_id: int | None = Field(default=None, gt=0)
    occupant_locked: bool = False


class CompositionPreviewRequest(BaseModel):
    """Preview de composição manual: participantes previstos + prancheta.

    `manual_include_member_ids`/`excluded_member_ids` ajustam a lista de
    confirmados do treino vinculado (DECISOES.md: "Começar com confirmados e
    permitir inclusão/exclusão planejada explícita"). Nada aqui é persistido;
    o preview é recalculado a cada chamada.
    """

    manual_include_member_ids: list[int] = Field(default_factory=list, max_length=40)
    excluded_member_ids: list[int] = Field(default_factory=list, max_length=40)
    blocks: list[CompositionBlockInput] = Field(min_length=1, max_length=12)
    assignments: list[CompositionAssignmentInput] = Field(default_factory=list, max_length=800)
    # Ataque forte × defesa forte é o padrão desde 23/09/2026; Equilibrado
    # continua com o mesmo acesso e destaque.
    mode: Literal["EQUILIBRADO", "DIRECIONADO"] = "DIRECIONADO"
    suggest: bool = False

    @field_validator("manual_include_member_ids", "excluded_member_ids")
    @classmethod
    def positive_member_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("Os IDs de atleta devem ser positivos.")
        return value

    @model_validator(mode="after")
    def validate_unique_block_ids(self) -> "CompositionPreviewRequest":
        block_ids = [block.block_id for block in self.blocks]
        if len(set(block_ids)) != len(block_ids):
            raise ValueError("Os blocos precisam ter block_id únicos.")
        return self


class GuidedFinishInput(BaseModel):
    playbook_session_id: int | None = Field(default=None, gt=0)
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


# ---------------------------------------------------------------------------
# Jogada desenhada (docs/planejamento-treinos/JOGADAS.md)
# ---------------------------------------------------------------------------

PLAY_ATTACK_POSITIONS = ("GOL", "PE", "ME", "C", "MD", "PD", "PV")
PLAY_DEFENSE_POSITIONS = ("GOL", "M1", "M2", "M3", "AVANCADO")
# Meia quadra em metros: origem no centro da linha de gol, x para a direita
# de quem ataca, y em direção ao meio da quadra.
PLAY_HALF_COURT = {"x_min": -10.0, "x_max": 10.0, "y_min": 0.0, "y_max": 20.0}
_PLAY_ID = r"^[a-z0-9][a-z0-9-]{0,23}$"


class PlayPoint(BaseModel):
    x: float = Field(ge=PLAY_HALF_COURT["x_min"], le=PLAY_HALF_COURT["x_max"])
    y: float = Field(ge=PLAY_HALF_COURT["y_min"], le=PLAY_HALF_COURT["y_max"])


class PlayActor(BaseModel):
    id: str = Field(pattern=_PLAY_ID)
    side: Literal["ATTACK", "DEFENSE"]
    position: str = Field(max_length=10)
    label: str = Field(default="", max_length=24)
    start: PlayPoint

    @field_validator("label")
    @classmethod
    def strip_actor_label(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_position(self) -> "PlayActor":
        self.position = self.position.strip().upper()
        allowed = PLAY_ATTACK_POSITIONS if self.side == "ATTACK" else PLAY_DEFENSE_POSITIONS
        if self.position not in allowed:
            raise ValueError(f"Posição {self.position or '(vazia)'} não existe para {'ataque' if self.side == 'ATTACK' else 'defesa'}.")
        return self


class PlayAction(BaseModel):
    type: Literal["MOVE", "PASS", "DRIBBLE", "SHOT", "SCREEN", "CURTAIN", "FEINT"]
    actor: str | None = Field(default=None, pattern=_PLAY_ID)
    target: str | None = Field(default=None, pattern=_PLAY_ID)
    to: PlayPoint | None = None
    via: list[PlayPoint] = Field(default_factory=list, max_length=3)
    at: float = Field(default=0.7, ge=0.0, le=1.0)
    kind: Literal["DIRECT", "BOUNCE", "LOB"] = "DIRECT"
    zone: int | None = Field(default=None, ge=1, le=9)

    @model_validator(mode="after")
    def validate_shape(self) -> "PlayAction":
        if not self.actor:
            raise ValueError("Toda ação precisa de uma atleta.")
        if self.type in {"MOVE", "DRIBBLE"} and self.to is None:
            raise ValueError("Deslocamento e drible precisam de destino.")
        if self.type in {"PASS", "SCREEN", "CURTAIN"} and not self.target:
            raise ValueError("Passe, bloqueio e cortina precisam de quem recebe ou de quem é bloqueada.")
        if self.type not in {"MOVE", "DRIBBLE"} and (self.via or (self.to is not None and self.type != "SCREEN")):
            raise ValueError("Só deslocamento e drible têm trajetória.")
        return self


class PlayStep(BaseModel):
    id: str = Field(pattern=_PLAY_ID)
    label: str = Field(default="", max_length=80)
    duration_s: float = Field(default=2.0, ge=0.5, le=10.0)
    note: str = Field(default="", max_length=500)
    actions: list[PlayAction] = Field(default_factory=list, max_length=24)

    @field_validator("label", "note")
    @classmethod
    def strip_step_text(cls, value: str) -> str:
        return value.strip()


class PlayBall(BaseModel):
    holder: str | None = Field(default=None, pattern=_PLAY_ID)


class PlayDiagram(BaseModel):
    court: Literal["HALF"] = "HALF"
    defense_system: Literal["6x0", "5x1", "3x2", "4x2"] | None = None
    actors: list[PlayActor] = Field(min_length=1, max_length=16)
    ball: PlayBall = Field(default_factory=PlayBall)
    steps: list[PlayStep] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_play(self) -> "PlayDiagram":
        actors = {actor.id: actor for actor in self.actors}
        if len(actors) != len(self.actors):
            raise ValueError("Cada atleta da jogada precisa de um identificador único.")
        step_ids = [step.id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("Cada passo precisa de um identificador único.")
        holder = self.ball.holder
        if holder is not None and holder not in actors:
            raise ValueError("A bola começa com uma atleta que não está na jogada.")
        for number, step in enumerate(self.steps, start=1):
            moved: set[str] = set()
            for action in step.actions:
                for reference in (action.actor, action.target):
                    if reference is not None and reference not in actors:
                        raise ValueError(f"Passo {number}: atleta {reference} não está na jogada.")
                if action.type in {"MOVE", "DRIBBLE"}:
                    if action.actor in moved:
                        raise ValueError(f"Passo {number}: cada atleta se desloca uma vez por passo.")
                    moved.add(str(action.actor))
            # Posse: passes, dribles e arremessos na ordem em que acontecem.
            for action in sorted(
                (item for item in step.actions if item.type in {"PASS", "DRIBBLE", "SHOT"}),
                key=lambda item: (item.at if item.type != "DRIBBLE" else 0.0),
            ):
                if action.actor != holder:
                    label = {"PASS": "passar", "DRIBBLE": "driblar", "SHOT": "arremessar"}[action.type]
                    raise ValueError(f"Passo {number}: só quem está com a bola pode {label}.")
                if action.type == "PASS":
                    if action.target == action.actor:
                        raise ValueError(f"Passo {number}: o passe precisa ir para outra atleta.")
                    holder = action.target
                elif action.type == "SHOT":
                    holder = None
        return self


class PlayDiagramInput(BaseModel):
    base_revision: int | None = Field(default=None, ge=1)
    change_summary: str = Field(default="", max_length=500)
    diagram: PlayDiagram

    @field_validator("change_summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        return value.strip()
