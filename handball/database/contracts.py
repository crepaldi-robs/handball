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
    ) -> list[dict[str, Any]]: ...

    def get_event(self, event_id: int, team_ids: Iterable[int]) -> dict[str, Any] | None: ...

    def create_event(self, payload: Mapping[str, Any], *, actor_user_id: int) -> dict[str, Any]: ...

    def update_event(
        self,
        event_id: int,
        payload: Mapping[str, Any],
        *,
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
