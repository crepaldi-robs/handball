from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date
from typing import (
    Any,
    BinaryIO,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Protocol,
    TypedDict,
    runtime_checkable,
)


class DatabaseCompatibilityError(RuntimeError):
    """O banco persistente está ausente, corrompido ou incompatível."""


class MemberDTO(TypedDict, total=False):
    id: int
    name: str
    position: str
    active: int
    created_at: str
    updated_at: str


class TrainingSessionDTO(TypedDict, total=False):
    id: int
    training_date: str
    notes: str
    is_finalized: int
    created_at: str
    updated_at: str


class AttendanceRecordDTO(TypedDict, total=False):
    record_id: int
    session_id: int
    member_id: int
    name: str
    position: str
    confirmation_status: str
    present: int | None
    notes: str
    version: int
    updated_at: str


class AttendanceUpdateDTO(TypedDict, total=False):
    member_id: int
    confirmation_status: str
    present: bool | None
    notes: str


class SyncOperationDTO(AttendanceUpdateDTO, total=False):
    operation_id: str
    base_version: int


class SyncResultDTO(TypedDict, total=False):
    operation_id: str
    status: str
    changed: bool
    record: AttendanceRecordDTO


@runtime_checkable
class AttendanceRepositoryContract(Protocol):
    """Contrato estável consumido pelo módulo de presenças."""

    def get_or_create_session(
        self,
        training_date: date | str,
        *,
        actor_user_id: int | None = None,
    ) -> dict[str, Any]: ...

    def ensure_attendance_records(self, session_id: int) -> None: ...

    def get_session(self, session_id: int) -> dict[str, Any]: ...

    def get_session_records(self, session_id: int) -> list[dict[str, Any]]: ...

    def save_records(
        self,
        session_id: int,
        updates: Iterable[Mapping[str, Any]],
        *,
        source: str = "ui",
        actor_user_id: int | None = None,
    ) -> int: ...

    def sync_records(
        self,
        session_id: int,
        operations: Iterable[Mapping[str, Any]],
        *,
        source: str = "pwa",
        actor_user_id: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def finalize_session(self, session_id: int, *, source: str = "ui", actor_user_id: int | None = None) -> int: ...

    def reopen_session(self, session_id: int, *, source: str = "ui", actor_user_id: int | None = None) -> None: ...

    def update_session_notes(self, session_id: int, notes: str, *, source: str = "ui", actor_user_id: int | None = None) -> None: ...

    def get_history(self) -> list[dict[str, Any]]: ...

    def get_audit_log(self, limit: int = 500) -> list[dict[str, Any]]: ...

    def list_members(
        self,
        *,
        include_inactive: bool = True,
    ) -> list[dict[str, Any]]: ...

    def add_member(self, name: str, position: str, *, actor_user_id: int | None = None) -> None: ...

    def update_member(
        self,
        member_id: int,
        *,
        position: str,
        active: bool,
        actor_user_id: int | None = None,
    ) -> None: ...


@runtime_checkable
class CalendarRepositoryContract(Protocol):
    """Contrato de persistência consumido pelo módulo Calendário."""

    def list_options(self, team_ids: Iterable[int]) -> dict[str, list[dict[str, Any]]]: ...

    def list_events(
        self,
        team_ids: Iterable[int],
        *,
        season_id: int | None = None,
        season_label: str | None = None,
        starts_from: str | None = None,
        ends_to: str | None = None,
        event_types: Iterable[str] = (),
        statuses: Iterable[str] = (),
        query: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_event(self, event_id: int, team_ids: Iterable[int]) -> dict[str, Any] | None: ...

    def list_training_events(
        self,
        team_ids: Iterable[int],
        *,
        season_id: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def list_countdown_targets(
        self,
        team_ids: Iterable[int],
        *,
        season_id: int | None = None,
        season_label: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_or_create_attendance_session(
        self,
        event_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def get_training_event_for_session(
        self,
        session_id: int,
        team_ids: Iterable[int],
    ) -> dict[str, Any] | None: ...

    def create_event(self, payload: Mapping[str, Any], *, actor_user_id: int) -> dict[str, Any]: ...

    def update_event(
        self,
        event_id: int,
        payload: Mapping[str, Any],
        *,
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def check_conflicts(
        self,
        team_ids: Iterable[int],
        *,
        team_id: int,
        starts_at: str,
        ends_at: str,
        event_id: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_command_receipt(
        self,
        operation_id: str,
        *,
        actor_user_id: int,
        request_hash: str,
    ) -> dict[str, Any] | None: ...

    def store_command_receipt(
        self,
        operation_id: str,
        *,
        actor_user_id: int,
        request_hash: str,
        response: Mapping[str, Any],
    ) -> None: ...

    def transition_event(
        self,
        event_id: int,
        *,
        action: str,
        team_ids: Iterable[int],
        actor_user_id: int,
        reason: str = "",
        base_version: int | None = None,
    ) -> dict[str, Any]: ...

    def reschedule_event(
        self,
        event_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        starts_at: str,
        ends_at: str,
        reason: str,
        base_version: int | None = None,
    ) -> dict[str, Any]: ...

    def event_history(
        self,
        event_id: int,
        *,
        team_ids: Iterable[int],
    ) -> list[dict[str, Any]]: ...

    def create_series(
        self,
        payload: Mapping[str, Any],
        occurrences: Iterable[Mapping[str, Any]],
        *,
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def update_series(
        self,
        series_id: int,
        payload: Mapping[str, Any],
        *,
        scope: str,
        anchor_event_id: int,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def list_justifications(
        self,
        *,
        player_member_id: int,
        team_ids: Iterable[int],
    ) -> list[dict[str, Any]]: ...

    def upsert_justification(
        self,
        event_id: int,
        *,
        player_member_id: int,
        user_id: int,
        reason: str,
        team_ids: Iterable[int],
    ) -> dict[str, Any]: ...

    def update_justification(
        self,
        justification_id: int,
        *,
        player_member_id: int,
        user_id: int,
        reason: str,
        team_ids: Iterable[int],
    ) -> dict[str, Any]: ...


@runtime_checkable
class PlaybookRepositoryContract(Protocol):
    """Contrato de persistência consumido pelo módulo Playbook."""

    def is_available(self) -> bool: ...

    def active_team_ids(self) -> tuple[int, ...]: ...

    def teams(self, team_ids: Iterable[int]) -> list[dict[str, Any]]: ...

    def tree(
        self,
        team_ids: Iterable[int],
        *,
        include_archived: bool = False,
    ) -> dict[str, Any]: ...

    def list_contents(
        self,
        team_ids: Iterable[int],
        *,
        folder_id: int | None = None,
        query: str | None = None,
        perspective: str | None = None,
        position: str | None = None,
        published_only: bool = False,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    def user_collections(
        self,
        *,
        user_id: int,
        team_ids: Iterable[int],
        published_only: bool,
    ) -> dict[str, list[dict[str, Any]]]: ...

    def next_training_event_id(self, team_ids: Iterable[int]) -> int | None: ...

    def plan_for_event(
        self,
        event_id: int,
        *,
        team_ids: Iterable[int],
        published_only: bool = False,
    ) -> dict[str, Any]: ...

    def content_detail(
        self,
        content_id: int,
        *,
        team_ids: Iterable[int],
        published_only: bool = False,
    ) -> dict[str, Any]: ...

    def mark_recent_view(
        self,
        content_id: int,
        *,
        user_id: int,
        team_ids: Iterable[int],
        published_only: bool,
    ) -> None: ...

    def seed_initial_taxonomy(
        self, team_id: int, *, actor_user_id: int
    ) -> dict[str, Any]: ...

    def create_folder(
        self,
        team_id: int,
        *,
        name: str,
        parent_id: int | None,
        actor_user_id: int,
        sort_order: int | None = None,
    ) -> dict[str, Any]: ...

    def update_folder(
        self,
        folder_id: int,
        *,
        name: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def move_folder(
        self,
        folder_id: int,
        *,
        parent_id: int | None,
        sort_order: int | None,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def copy_folder_structure(
        self,
        folder_id: int,
        *,
        parent_id: int | None,
        name: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def reorder_folders(
        self,
        folder_ids: Iterable[int],
        *,
        parent_id: int | None,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> list[dict[str, Any]]: ...

    def folder_impact(
        self, folder_id: int, *, team_ids: Iterable[int]
    ) -> dict[str, Any]: ...

    def archive_folder(
        self,
        folder_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        restore: bool = False,
    ) -> dict[str, Any]: ...

    def hard_delete_folder(
        self,
        folder_id: int,
        *,
        confirmation: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def create_content(
        self,
        team_id: int,
        payload: Mapping[str, Any],
        *,
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def update_content(
        self,
        content_id: int,
        payload: Mapping[str, Any],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        change_note: str = "",
    ) -> dict[str, Any]: ...

    def move_contents(
        self,
        content_ids: Iterable[int],
        *,
        folder_id: int,
        operation: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> list[dict[str, Any]]: ...

    def set_content_status(
        self,
        content_id: int,
        *,
        status: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def list_revisions(
        self, content_id: int, *, team_ids: Iterable[int]
    ) -> list[dict[str, Any]]: ...

    def restore_revision(
        self,
        content_id: int,
        revision_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def set_relations(
        self,
        content_id: int,
        relations: Iterable[Mapping[str, Any]],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> list[dict[str, Any]]: ...

    def add_drive_attachment(
        self,
        content_id: int,
        *,
        url: str,
        label: str,
        offline_essential: bool,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def add_local_attachment(
        self,
        content_id: int,
        *,
        storage_key: str,
        label: str,
        mime_type: str,
        size_bytes: int,
        offline_essential: bool,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def attachment(
        self,
        attachment_id: int,
        *,
        team_ids: Iterable[int],
        published_only: bool = False,
    ) -> dict[str, Any]: ...

    def delete_attachment(
        self,
        attachment_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def toggle_favorite(
        self,
        content_id: int,
        *,
        user_id: int,
        team_ids: Iterable[int],
        published_only: bool,
    ) -> bool: ...

    def offline_essential_attachments(
        self,
        *,
        team_ids: Iterable[int],
        published_only: bool,
    ) -> list[dict[str, Any]]: ...

    def save_plan(
        self,
        event_id: int,
        payload: Mapping[str, Any],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def reuse_plan(
        self,
        event_id: int,
        *,
        source_event_id: int,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def record_evaluations(
        self,
        event_id: int,
        evaluations: Iterable[Mapping[str, Any]],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> list[dict[str, Any]]: ...

    def hard_delete_content(
        self,
        content_id: int,
        *,
        confirmation: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]: ...

    def transfer_plan_for_reschedule(
        self,
        source_event_id: int,
        replacement_event_id: int,
        *,
        actor_user_id: int,
        reason: str,
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class BackupDownload:
    """Artefato de download que não revela o caminho persistente ao consumidor."""

    filename: str
    media_type: str
    content_length: int
    _open_binary: Callable[[], BinaryIO] = field(repr=False, compare=False)

    def iter_bytes(self, *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        if chunk_size <= 0:
            raise ValueError("chunk_size deve ser positivo.")
        with self._open_binary() as source:
            for block in iter(lambda: source.read(chunk_size), b""):
                yield block


@runtime_checkable
class BackupProvider(Protocol):
    """Cria um download sem expor nomes ou caminhos de persistência ao módulo."""

    def create_backup_download(self) -> BackupDownload: ...


@runtime_checkable
class UnitOfWorkContract(Protocol):
    @property
    def attendance(self) -> AttendanceRepositoryContract: ...

    @property
    def identity(self) -> Any: ...

    @property
    def calendar(self) -> CalendarRepositoryContract: ...

    @property
    def playbook(self) -> PlaybookRepositoryContract: ...

    @property
    def sql_explorer(self) -> Any: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def __enter__(self) -> UnitOfWorkContract: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> bool: ...


@runtime_checkable
class UnitOfWorkFactoryContract(Protocol):
    def __call__(self, *, read_only: bool = False) -> UnitOfWorkContract: ...


RepositoryContext = AbstractContextManager[AttendanceRepositoryContract]
