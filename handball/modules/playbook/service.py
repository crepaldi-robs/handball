from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse
from uuid import uuid4

from handball.core.authorization import AccessContext, Permission
from handball.core.errors import PlaybookProblem
from handball.database.contracts import UnitOfWorkFactoryContract
from handball.modules.presencas.planner import confirmed_player_profiles, exercise_fit


MEDIA_LIMITS: dict[str, int] = {
    "image/jpeg": 20 * 1024 * 1024,
    "image/png": 20 * 1024 * 1024,
    "image/webp": 20 * 1024 * 1024,
    "image/gif": 20 * 1024 * 1024,
    "application/pdf": 50 * 1024 * 1024,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": 50 * 1024 * 1024,
    "video/mp4": 250 * 1024 * 1024,
    "video/webm": 250 * 1024 * 1024,
}
MEDIA_SUFFIXES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


@dataclass(frozen=True)
class LocalMediaDownload:
    path: Path
    filename: str
    media_type: str


def _sniff_media(data: bytes) -> str | None:
    """Identifica formatos aceitos pelo conteúdo, sem confiar no MIME enviado."""

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
            if "[Content_Types].xml" in names and any(
                name.startswith("ppt/") for name in names
            ):
                return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        except (OSError, zipfile.BadZipFile):
            return None
    return None


class PlaybookService:
    """Casos de uso do Playbook, sempre sobre contratos/UoW centrais."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactoryContract,
        media_root: Path,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._media_root = Path(media_root)

    @staticmethod
    def _has_manage(context: AccessContext) -> bool:
        return Permission.PLAYBOOK_MANAGE in context.permissions

    @staticmethod
    def _published_only(context: AccessContext) -> bool:
        return Permission.PLAYBOOK_MANAGE not in context.permissions

    @staticmethod
    def _require(context: AccessContext, permission: Permission) -> None:
        if permission not in context.permissions:
            raise PermissionError("Sua conta não possui a permissão necessária no Playbook.")

    def _require_available(self) -> None:
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            if unit_of_work.playbook.is_available():
                return
        raise PlaybookProblem(
            code="playbook.upgrade_required",
            title="Atualização do Playbook necessária",
            message="Este módulo depende da migração versionada do Playbook, que ainda não foi aplicada.",
            suggestion="Peça a abertura da janela DB_MIGRATION; a aplicação não cria tabelas nem estrutura automaticamente.",
            status_code=409,
        )

    def _team_ids(
        self,
        context: AccessContext,
        requested_team_id: int | None = None,
    ) -> tuple[int, ...]:
        self._require_available()
        allowed = {int(value) for value in context.team_ids}
        # DEV é a autoridade administrativa existente neste produto. Ele recebe
        # escopo de equipes pelo repositório, nunca pela interface ou por SQL no
        # módulo. ADMIN é aceito para uma futura migração de papéis.
        if ("DEV" in context.system_roles or "ADMIN" in context.system_roles) and self._has_manage(context):
            with self._unit_of_work_factory(read_only=True) as unit_of_work:
                allowed.update(unit_of_work.playbook.active_team_ids())
        if requested_team_id is not None:
            if int(requested_team_id) not in allowed:
                raise PermissionError("A equipe escolhida está fora do escopo da sua conta.")
            return (int(requested_team_id),)
        if not allowed:
            raise PermissionError("Sua conta não possui uma equipe ativa para consultar no Playbook.")
        return tuple(sorted(allowed))

    def page_context(self, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_READ)
        team_ids = self._team_ids(context)
        return {
            "team_ids": team_ids,
            "can_manage": self._has_manage(context),
            "published_only": self._published_only(context),
        }

    def library(
        self,
        context: AccessContext,
        *,
        team_id: int | None,
        folder_id: int | None,
        query: str | None,
        perspective: str | None = None,
        position: str | None = None,
        include_archived: bool,
    ) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_READ)
        can_manage = self._has_manage(context)
        team_ids = self._team_ids(context, team_id)
        if include_archived and not can_manage:
            raise PermissionError("Conteúdo arquivado só é visível para a comissão técnica.")
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            teams = unit_of_work.playbook.teams(team_ids)
            tree = unit_of_work.playbook.tree(team_ids, include_archived=include_archived and can_manage)
            contents = unit_of_work.playbook.list_contents(
                team_ids,
                folder_id=folder_id,
                query=query,
                perspective=perspective,
                position=position,
                published_only=not can_manage,
                include_archived=include_archived and can_manage,
            )
            collections = unit_of_work.playbook.user_collections(
                user_id=context.user_id,
                team_ids=team_ids,
                published_only=not can_manage,
            )
            next_event_id = unit_of_work.playbook.next_training_event_id(
                team_ids,
                player_visible_only=not can_manage,
            )
            next_plan = (
                unit_of_work.playbook.plan_for_event(
                    next_event_id,
                    team_ids=team_ids,
                    published_only=not can_manage,
                    player_visible_only=not can_manage,
                )
                if next_event_id is not None
                else None
            )
        return {
            "team_ids": list(team_ids),
            "teams": teams,
            "can_manage": can_manage,
            "tree": tree,
            "contents": contents,
            **collections,
            "next_training": next_plan,
        }

    def folders(
        self,
        context: AccessContext,
        *,
        team_id: int | None,
        include_archived: bool,
    ) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_READ)
        can_manage = self._has_manage(context)
        if include_archived and not can_manage:
            raise PermissionError("Pastas arquivadas só são visíveis para a comissão técnica.")
        team_ids = self._team_ids(context, team_id)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.playbook.tree(
                team_ids,
                include_archived=include_archived and can_manage,
            )

    def content(self, content_id: int, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_READ)
        team_ids = self._team_ids(context)
        published_only = self._published_only(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            result = unit_of_work.playbook.content_detail(
                content_id,
                team_ids=team_ids,
                published_only=published_only,
            )
            if self._has_manage(context):
                result["revisions"] = unit_of_work.playbook.list_revisions(
                    content_id,
                    team_ids=team_ids,
                )
        return result

    def content_fit(self, content_id: int, event_id: int, context: AccessContext) -> dict[str, Any]:
        """Filtro "Fecha com os confirmados" (handoff HM-IME §7, B3).

        Só orquestra dado que já existe: as variantes/papéis do próprio
        conteúdo (content_detail, já lido pela tela) e os confirmados do
        treino (mesma leitura que build_coach_report faz para a chamada da
        CT). Nenhuma tabela, coluna ou campo persistido novo — ver AGENTS.md
        regra 13/19 e a decisão registrada no handoff de design.
        """

        self._require(context, Permission.PLAYBOOK_MANAGE)
        team_ids = self._team_ids(context)
        published_only = self._published_only(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            detail = unit_of_work.playbook.content_detail(
                content_id, team_ids=team_ids, published_only=published_only
            )
            variants = detail.get("exercise_variants") or []
            event = next(
                (
                    item
                    for item in unit_of_work.calendar.list_training_events(team_ids)
                    if int(item["id"]) == int(event_id)
                ),
                None,
            )
            if event is None:
                raise KeyError("Treino não encontrado.")
            session_id = event.get("attendance_session_id")
            confirmed = (
                confirmed_player_profiles(unit_of_work.attendance.get_session_records(int(session_id)))
                if session_id
                else []
            )
        return {
            "content_id": int(content_id),
            "event_id": int(event_id),
            "confirmed_count": len(confirmed),
            "variants": exercise_fit(confirmed, variants),
        }

    def mark_view(self, content_id: int, context: AccessContext) -> None:
        """Registra a consulta pessoal somente por comando CSRF protegido."""

        self._require(context, Permission.PLAYBOOK_READ)
        team_ids = self._team_ids(context)
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.playbook.mark_recent_view(
                content_id,
                user_id=context.user_id,
                team_ids=team_ids,
                published_only=self._published_only(context),
            )

    def seed_taxonomy(self, context: AccessContext, team_id: int) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        team_ids = self._team_ids(context, team_id)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.seed_initial_taxonomy(
                int(team_ids[0]), actor_user_id=context.user_id
            )

    def create_folder(self, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        team_ids = self._team_ids(context, body.team_id)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.create_folder(
                int(team_ids[0]),
                name=body.name,
                parent_id=body.parent_id,
                sort_order=body.sort_order,
                actor_user_id=context.user_id,
            )

    def rename_folder(self, folder_id: int, name: str, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.update_folder(
                folder_id,
                name=name,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def move_folder(self, folder_id: int, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.move_folder(
                folder_id,
                parent_id=body.parent_id,
                sort_order=body.sort_order,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def copy_folder_structure(self, folder_id: int, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.copy_folder_structure(
                folder_id,
                parent_id=body.parent_id,
                name=body.name,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def reorder_folders(self, body: Any, context: AccessContext) -> list[dict[str, Any]]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.reorder_folders(
                body.folder_ids,
                parent_id=body.parent_id,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def folder_impact(self, folder_id: int, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.playbook.folder_impact(folder_id, team_ids=self._team_ids(context))

    def archive_folder(self, folder_id: int, context: AccessContext, *, restore: bool) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.archive_folder(
                folder_id,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
                restore=restore,
            )

    def delete_folder(self, folder_id: int, confirmation: str, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.hard_delete_folder(
                folder_id,
                confirmation=confirmation,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def create_content(self, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        team_ids = self._team_ids(context, body.team_id)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.create_content(
                int(team_ids[0]),
                body.model_dump(exclude={"team_id", "change_note"}),
                actor_user_id=context.user_id,
            )

    def update_content(self, content_id: int, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        team_ids = self._team_ids(context, body.team_id)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.update_content(
                content_id,
                body.model_dump(exclude={"team_id", "change_note"}),
                team_ids=team_ids,
                actor_user_id=context.user_id,
                change_note=body.change_note,
            )

    def move_contents(self, body: Any, context: AccessContext) -> list[dict[str, Any]]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.move_contents(
                body.content_ids,
                folder_id=body.folder_id,
                operation=body.operation,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def set_content_status(self, content_id: int, status: str, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.set_content_status(
                content_id,
                status=status,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def revisions(self, content_id: int, context: AccessContext) -> list[dict[str, Any]]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.playbook.list_revisions(content_id, team_ids=self._team_ids(context))

    def restore_revision(self, content_id: int, revision_id: int, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.restore_revision(
                content_id,
                revision_id,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def set_relations(self, content_id: int, relations: Iterable[Mapping[str, Any]], context: AccessContext) -> list[dict[str, Any]]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.set_relations(
                content_id,
                relations,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def add_drive_attachment(self, content_id: int, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.add_drive_attachment(
                content_id,
                url=body.url,
                label=body.label,
                offline_essential=body.offline_essential,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def _safe_media_path(self, storage_key: str) -> Path:
        root = self._media_root.expanduser().resolve()
        candidate = (root / storage_key).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise PlaybookProblem(
                code="playbook.invalid_media_path",
                title="Arquivo de mídia inválido",
                message="O caminho salvo para este anexo não é seguro.",
                suggestion="Remova o anexo e envie-o novamente.",
                status_code=409,
            ) from exc
        return candidate

    @staticmethod
    def _validate_upload(filename: str, data: bytes) -> tuple[str, str]:
        media_type = _sniff_media(data)
        if media_type is None or media_type not in MEDIA_LIMITS:
            raise PlaybookProblem(
                code="playbook.unsupported_media",
                title="Arquivo não aceito",
                message="Envie uma imagem, MP4/WebM, PDF ou apresentação PPTX válida.",
                suggestion="Confira o arquivo original e tente novamente.",
                field="file",
                status_code=422,
            )
        if len(data) > MEDIA_LIMITS[media_type]:
            limit_mib = MEDIA_LIMITS[media_type] // (1024 * 1024)
            raise PlaybookProblem(
                code="playbook.media_too_large",
                title="Arquivo maior que o limite permitido",
                message=f"Este tipo de arquivo aceita no máximo {limit_mib} MiB.",
                suggestion="Reduza o arquivo ou use um link do Drive.",
                field="file",
                status_code=413,
            )
        if not data:
            raise PlaybookProblem(
                code="playbook.empty_media",
                title="Arquivo vazio",
                message="O arquivo enviado não contém dados.",
                suggestion="Escolha o arquivo novamente e tente enviar.",
                field="file",
                status_code=422,
            )
        return media_type, MEDIA_SUFFIXES[media_type]

    def upload_attachment(
        self,
        content_id: int,
        *,
        filename: str,
        label: str,
        offline_essential: bool,
        data: bytes,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        media_type, suffix = self._validate_upload(filename, data)
        root = self._media_root.expanduser()
        try:
            root.mkdir(parents=True, exist_ok=True)
            root = root.resolve()
        except OSError as exc:
            raise PlaybookProblem(
                code="playbook.media_storage_unavailable",
                title="Não foi possível preparar o armazenamento de mídia",
                message="O arquivo não foi registrado no Playbook.",
                suggestion="Verifique a pasta de dados da aplicação e tente novamente.",
                status_code=503,
            ) from exc
        storage_key = f"{uuid4().hex}{suffix}"
        final_path = self._safe_media_path(storage_key)
        temporary_path = self._safe_media_path(f".{storage_key}.{uuid4().hex}.upload")
        safe_label = str(label or "").strip()[:200] or Path(filename or "anexo").name[:200]
        try:
            temporary_path.write_bytes(data)
            with self._unit_of_work_factory() as unit_of_work:
                result = unit_of_work.playbook.add_local_attachment(
                    content_id,
                    storage_key=storage_key,
                    label=safe_label,
                    mime_type=media_type,
                    size_bytes=len(data),
                    offline_essential=offline_essential,
                    team_ids=self._team_ids(context),
                    actor_user_id=context.user_id,
                )
                temporary_path.replace(final_path)
            return result
        except OSError as exc:
            try:
                final_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise PlaybookProblem(
                code="playbook.media_write_failed",
                title="Não foi possível salvar o arquivo",
                message="O conteúdo não foi alterado por esse envio.",
                suggestion="Confira o espaço disponível e tente novamente.",
                status_code=503,
            ) from exc
        except Exception:
            # Se o commit falhar depois da troca atômica do temporário, não
            # deixamos um arquivo órfão que não possui metadado autorizado.
            try:
                final_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        finally:
            temporary_path.unlink(missing_ok=True)

    def delete_attachment(self, attachment_id: int, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            deleted = unit_of_work.playbook.delete_attachment(
                attachment_id,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )
        cleanup_warning = False
        if deleted["storage_kind"] == "LOCAL_FILE":
            try:
                self._safe_media_path(str(deleted["storage_key"])).unlink(missing_ok=True)
            except OSError:
                # O registro já saiu de forma auditada. Não retorne falha que
                # induza o CT a repetir a exclusão; uma limpeza posterior é segura.
                cleanup_warning = True
        return {"deleted": True, "attachment_id": int(attachment_id), "cleanup_warning": cleanup_warning}

    def local_media(self, attachment_id: int, context: AccessContext) -> LocalMediaDownload:
        self._require(context, Permission.PLAYBOOK_READ)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            attachment = unit_of_work.playbook.attachment(
                attachment_id,
                team_ids=self._team_ids(context),
                published_only=self._published_only(context),
            )
        if attachment["storage_kind"] != "LOCAL_FILE":
            raise ValueError("Este anexo é um link externo e não possui download local.")
        path = self._safe_media_path(str(attachment["storage_key"]))
        if not path.is_file():
            raise PlaybookProblem(
                code="playbook.media_missing",
                title="Arquivo não localizado",
                message="O registro do anexo existe, mas o arquivo não está disponível no armazenamento protegido.",
                suggestion="Peça ao CT para enviar o arquivo novamente.",
                status_code=404,
            )
        filename = str(attachment.get("label") or path.name).replace("\r", " ").replace("\n", " ")
        return LocalMediaDownload(path=path, filename=filename[:200] or path.name, media_type=str(attachment["mime_type"]))

    def drive_link(self, attachment_id: int, context: AccessContext) -> str:
        self._require(context, Permission.PLAYBOOK_READ)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            attachment = unit_of_work.playbook.attachment(
                attachment_id,
                team_ids=self._team_ids(context),
                published_only=self._published_only(context),
            )
        if attachment["storage_kind"] != "DRIVE_LINK":
            raise ValueError("Este anexo é armazenado localmente.")
        url = str(attachment["url"] or "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "drive.google.com",
            "docs.google.com",
        }:
            raise PlaybookProblem(
                code="playbook.invalid_external_link",
                title="O link deste material não é seguro",
                message="O registro não aponta para um link HTTPS permitido do Google Drive.",
                suggestion="Peça ao CT para revisar o material antes de abri-lo.",
                status_code=409,
            )
        return url

    def toggle_favorite(self, content_id: int, context: AccessContext) -> dict[str, bool]:
        self._require(context, Permission.PLAYBOOK_READ)
        with self._unit_of_work_factory() as unit_of_work:
            favorite = unit_of_work.playbook.toggle_favorite(
                content_id,
                user_id=context.user_id,
                team_ids=self._team_ids(context),
                published_only=self._published_only(context),
            )
        return {"favorite": favorite}

    def offline_manifest(self, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_READ)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            attachments = unit_of_work.playbook.offline_essential_attachments(
                team_ids=self._team_ids(context),
                published_only=self._published_only(context),
            )
        # Vídeos e Drive permanecem online; somente anexos locais essenciais e
        # não-vídeo podem ser cacheados pelo dispositivo mediante ação explícita.
        items = [
            {
                **item,
                "download_url": f"/api/v1/playbook/attachments/{item['id']}/download",
            }
            for item in attachments
            if item["storage_kind"] == "LOCAL_FILE"
            and not str(item["mime_type"]).startswith("video/")
        ]
        return {"items": items}

    # ------------------------------------------------------------------
    # PB-3B: planejamento independente do calendário
    # ------------------------------------------------------------------
    def list_plans(
        self,
        context: AccessContext,
        *,
        team_id: int | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.playbook.list_plans(
                team_ids=self._team_ids(context, team_id),
                include_archived=include_archived,
            )

    def plan_detail(self, plan_id: int, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.playbook.plan_detail(
                plan_id,
                team_ids=self._team_ids(context),
            )

    def save_independent_plan(
        self,
        body: Any,
        context: AccessContext,
        *,
        plan_id: int | None = None,
    ) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        payload = body.model_dump(mode="json", exclude_none=False)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.save_independent_plan(
                payload,
                plan_id=plan_id,
                team_ids=self._team_ids(context, payload.get("team_id")),
                actor_user_id=context.user_id,
            )

    def restore_plan_revision(
        self,
        plan_id: int,
        revision_id: int,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.restore_plan_revision(
                plan_id,
                revision_id,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def list_series(
        self,
        context: AccessContext,
        *,
        team_id: int | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.playbook.list_series(
                team_ids=self._team_ids(context, team_id),
                include_archived=include_archived,
            )

    def save_series(
        self,
        body: Any,
        context: AccessContext,
        *,
        series_id: int | None = None,
    ) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        payload = body.model_dump(mode="json", exclude_none=False)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.save_series(
                payload,
                series_id=series_id,
                team_ids=self._team_ids(context, payload.get("team_id")),
                actor_user_id=context.user_id,
            )

    def list_sessions(
        self,
        context: AccessContext,
        *,
        team_id: int | None = None,
        event_id: int | None = None,
        future_only: bool = False,
    ) -> list[dict[str, Any]]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.playbook.list_sessions(
                team_ids=self._team_ids(context, team_id),
                event_id=event_id,
                future_only=future_only,
            )

    def session_detail(self, session_id: int, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            return unit_of_work.playbook.session_detail(
                session_id,
                team_ids=self._team_ids(context),
            )

    def save_session(
        self,
        body: Any,
        context: AccessContext,
        *,
        session_id: int | None = None,
    ) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        payload = body.model_dump(mode="json", exclude_none=False)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.save_session(
                payload,
                session_id=session_id,
                team_ids=self._team_ids(context, payload.get("team_id")),
                actor_user_id=context.user_id,
            )

    def link_session_event(self, session_id: int, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.link_session_event(
                session_id,
                body.event_id,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
                reason=body.reason,
            )

    def unlink_session_event(self, session_id: int, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.unlink_session_event(
                session_id,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
                reason=body.reason,
            )

    def restore_session_revision(
        self,
        session_id: int,
        revision_id: int,
        context: AccessContext,
    ) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.restore_session_revision(
                session_id,
                revision_id,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def execute_session(self, session_id: int, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.execute_session(
                session_id,
                body.model_dump(mode="json"),
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def evaluate_session(
        self,
        session_id: int,
        body: Any,
        context: AccessContext,
    ) -> list[dict[str, Any]]:
        """Registra domínio da sessão sem exigir um evento de calendário."""

        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.record_session_evaluations(
                session_id,
                [item.model_dump() for item in body.evaluations],
                calendar_event_id=body.calendar_event_id,
                change_summary=body.change_summary,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def plan(self, event_id: int, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_READ)
        team_ids = self._team_ids(context)
        published_only = self._published_only(context)
        with self._unit_of_work_factory(read_only=True) as unit_of_work:
            if published_only:
                next_event_id = unit_of_work.playbook.next_training_event_id(
                    team_ids,
                    player_visible_only=True,
                )
                if next_event_id != int(event_id):
                    raise PermissionError("Atletas podem consultar apenas a sessão do próximo treino publicado e aberto.")
            return unit_of_work.playbook.plan_for_event(
                event_id,
                team_ids=team_ids,
                published_only=published_only,
                player_visible_only=published_only,
            )

    def save_plan(self, event_id: int, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.save_plan(
                event_id,
                body.model_dump(),
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def reuse_plan(self, event_id: int, source_event_id: int, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.playbook.reuse_plan(
                event_id,
                source_event_id=source_event_id,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )

    def guided_finish(self, event_id: int, body: Any, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        self._require(context, Permission.ATTENDANCE_FINALIZE)
        self._require(context, Permission.CALENDAR_MANAGE)
        team_ids = self._team_ids(context)
        with self._unit_of_work_factory() as unit_of_work:
            plan_payload = unit_of_work.playbook.plan_for_event(event_id, team_ids=team_ids)
            event = plan_payload["event"]
            selected_session_id = body.playbook_session_id
            linked_session_ids = {
                int(item["session"]["id"])
                for item in plan_payload.get("sessions") or ()
            }
            if selected_session_id is None or int(selected_session_id) not in linked_session_ids:
                raise PlaybookProblem(
                    code="playbook.session_destination_required",
                    title="Escolha a sessão do Playbook",
                    message="O fechamento do evento exige uma sessão de destino vinculada a este treino.",
                    suggestion="Selecione a sessão correspondente e tente novamente.",
                    status_code=409,
                )
            session_id = event.get("attendance_session_id")
            if session_id is None:
                raise PlaybookProblem(
                    code="playbook.attendance_required",
                    title="Abra a chamada antes de encerrar o treino",
                    message="O treino ainda não possui chamada oficial vinculada pelo Calendário.",
                    suggestion="Abra a chamada do treino, confira as presenças e volte para o fechamento guiado.",
                    status_code=409,
                )
            session = unit_of_work.attendance.get_session(int(session_id))
            if body.session_notes != str(session.get("notes") or ""):
                unit_of_work.attendance.update_session_notes(
                    int(session_id),
                    body.session_notes,
                    source="playbook-guided-finish",
                    actor_user_id=context.user_id,
                )
            if body.finalize_attendance and not bool(session["is_finalized"]):
                unit_of_work.attendance.finalize_session(
                    int(session_id),
                    source="playbook-guided-finish",
                    actor_user_id=context.user_id,
                )
            session = unit_of_work.attendance.get_session(int(session_id))
            if not bool(session["is_finalized"]):
                raise PlaybookProblem(
                    code="playbook.attendance_open",
                    title="A chamada ainda está aberta",
                    message="O treino só pode ser concluído depois de encerrar a chamada oficial.",
                    suggestion="Marque a opção de encerrar chamada ou volte à presença para concluí-la.",
                    status_code=409,
                )
            evaluations = unit_of_work.playbook.record_evaluations(
                event_id,
                [item.model_dump() for item in body.evaluations],
                team_ids=team_ids,
                actor_user_id=context.user_id,
                session_id=int(selected_session_id),
            )
            completed_event = unit_of_work.calendar.transition_event(
                event_id,
                action="COMPLETE",
                team_ids=team_ids,
                actor_user_id=context.user_id,
                reason="Fechamento guiado do Playbook",
                base_version=int(event["version"]),
            )
        return {
            "event": completed_event,
            "session": session,
            "evaluations": evaluations,
            "plan": self.plan(event_id, context),
        }

    def delete_content(self, content_id: int, confirmation: str, context: AccessContext) -> dict[str, Any]:
        self._require(context, Permission.PLAYBOOK_MANAGE)
        with self._unit_of_work_factory() as unit_of_work:
            result = unit_of_work.playbook.hard_delete_content(
                content_id,
                confirmation=confirmation,
                team_ids=self._team_ids(context),
                actor_user_id=context.user_id,
            )
        cleanup_warnings: list[int] = []
        for attachment in result.pop("attachments", []):
            if attachment["storage_kind"] != "LOCAL_FILE":
                continue
            try:
                self._safe_media_path(str(attachment["storage_key"])).unlink(missing_ok=True)
            except OSError:
                cleanup_warnings.append(int(attachment["id"]))
        result["cleanup_warnings"] = cleanup_warnings
        return result
