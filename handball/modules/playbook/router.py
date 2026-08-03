from __future__ import annotations

from typing import Annotated, Any, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from handball.core.auth import require_write_session, session_from_request
from handball.core.authorization import AccessContext, Permission, require_permission
from handball.core.errors import PlaybookProblem
from handball.modules.usuarios.service import IdentityService

from .schemas import (
    ContentInput,
    ContentMoveInput,
    ContentRelationsInput,
    ContentUpdateInput,
    DriveAttachmentInput,
    FolderCreateInput,
    FolderCopyInput,
    FolderMoveInput,
    FolderRenameInput,
    FolderReorderInput,
    GuidedFinishInput,
    IndependentPlanInput,
    PermanentDeleteInput,
    PlaybookSeriesInput,
    PlanReuseInput,
    PlaybookSessionInput,
    SessionEventLinkInput,
    SessionEvaluationInput,
    SessionExecutionInput,
    SessionUnlinkInput,
    TrainingPlanInput,
)
from .service import MEDIA_LIMITS, PlaybookService


def _write_permission(permission: Permission) -> Callable[[Request], AccessContext]:
    permission_dependency = require_permission(permission)

    def dependency(request: Request) -> AccessContext:
        context = permission_dependency(request)
        require_write_session(request)
        return context

    return dependency


def _handle_error(exc: Exception, request: Request | None = None) -> HTTPException:
    request_id = (
        request.headers.get("X-Request-ID") if request is not None else None
    ) or uuid4().hex[:12]
    if isinstance(exc, PlaybookProblem):
        return HTTPException(status_code=exc.status_code, detail=exc.to_detail(request_id=request_id))
    if isinstance(exc, PermissionError):
        problem = PlaybookProblem(
            code="playbook.permission_denied",
            title="Esta ação não está disponível para sua conta",
            message=str(exc) or "Sua conta não possui a permissão necessária.",
            suggestion="Volte à biblioteca ou peça ajuda à comissão técnica.",
            status_code=403,
        )
        return HTTPException(status_code=403, detail=problem.to_detail(request_id=request_id))
    if isinstance(exc, KeyError):
        problem = PlaybookProblem(
            code="playbook.not_found",
            title="Item não encontrado",
            message=str(exc).strip("'"),
            suggestion="Atualize a biblioteca e tente novamente.",
            status_code=404,
        )
        return HTTPException(status_code=404, detail=problem.to_detail(request_id=request_id))
    if isinstance(exc, ValueError):
        problem = PlaybookProblem(
            code="playbook.invalid_request",
            title="Não foi possível concluir a ação",
            message=str(exc),
            suggestion="Confira os campos informados e tente novamente; seus dados continuam preservados.",
            status_code=400,
        )
        return HTTPException(status_code=400, detail=problem.to_detail(request_id=request_id))
    if isinstance(exc, RuntimeError):
        problem = PlaybookProblem(
            code="playbook.upgrade_required",
            title="Atualização do Playbook necessária",
            message=str(exc),
            suggestion="A aplicação não alterou a base. Aplique a migração controlada antes de usar esta função.",
            status_code=409,
        )
        return HTTPException(status_code=409, detail=problem.to_detail(request_id=request_id))
    problem = PlaybookProblem(
        code="playbook.unexpected",
        title="Algo inesperado aconteceu",
        message="O Playbook não conseguiu concluir esta ação.",
        suggestion="Tente novamente. Se continuar, informe o código de suporte.",
        status_code=500,
    )
    return HTTPException(status_code=500, detail=problem.to_detail(request_id=request_id))


def create_router(service: PlaybookService, identity_service: IdentityService, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/app/playbook", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if Permission.PLAYBOOK_READ not in session.permissions:
            raise HTTPException(status_code=403)
        upgrade_required = False
        team_ids: list[int] = []
        try:
            page_context = service.page_context(session.to_access_context())
            team_ids = list(page_context["team_ids"])
        except PlaybookProblem:
            upgrade_required = True
        team_view = identity_service.resolve_active_team_view(session.to_access_context())
        return templates.TemplateResponse(
            request,
            "playbook/index.html",
            {
                "session": session,
                "organization": team_view["organization"],
                "team_theme": team_view["team_theme"],
                "can_manage": Permission.PLAYBOOK_MANAGE in session.permissions,
                "team_ids": team_ids,
                "upgrade_required": upgrade_required,
            },
        )

    @router.get("/api/v1/playbook")
    def library(
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_READ))],
        team_id: int | None = None,
        folder_id: int | None = None,
        q: str | None = None,
        perspective: str | None = None,
        position: str | None = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.library(
                context,
                team_id=team_id,
                folder_id=folder_id,
                query=q,
                perspective=perspective,
                position=position,
                include_archived=include_archived,
            )
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/folders/tree")
    def folder_tree(
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_READ))],
        team_id: int | None = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        try:
            return service.folders(
                context,
                team_id=team_id,
                include_archived=include_archived,
            )
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/taxonomy/seed")
    def seed_taxonomy(
        request: Request,
        body: dict[str, int],
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            team_id = int(body.get("team_id") or 0)
            if team_id <= 0:
                raise ValueError("Escolha a equipe para criar a estrutura inicial.")
            return service.seed_taxonomy(context, team_id)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/contents/{content_id}")
    def content(
        content_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_READ))],
    ) -> dict[str, Any]:
        try:
            return service.content(content_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/contents/{content_id}/view", status_code=204)
    def mark_content_view(
        content_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_READ))],
    ) -> Response:
        try:
            service.mark_view(content_id, context)
            return Response(status_code=204)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/folders", status_code=201)
    def create_folder(
        request: Request,
        body: FolderCreateInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.create_folder(body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/playbook/folders/{folder_id}")
    def rename_folder(
        folder_id: int,
        request: Request,
        body: FolderRenameInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.rename_folder(folder_id, body.name, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/folders/{folder_id}/move")
    def move_folder(
        folder_id: int,
        request: Request,
        body: FolderMoveInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.move_folder(folder_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/folders/{folder_id}/copy-structure", status_code=201)
    def copy_folder_structure(
        folder_id: int,
        request: Request,
        body: FolderCopyInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.copy_folder_structure(folder_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/folders/reorder")
    def reorder_folders(
        request: Request,
        body: FolderReorderInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return {"items": service.reorder_folders(body, context)}
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/folders/{folder_id}/impact")
    def folder_impact(
        folder_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.folder_impact(folder_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/folders/{folder_id}/archive")
    def archive_folder(
        folder_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.archive_folder(folder_id, context, restore=False)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/folders/{folder_id}/restore")
    def restore_folder(
        folder_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.archive_folder(folder_id, context, restore=True)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.delete("/api/v1/playbook/folders/{folder_id}")
    def delete_folder(
        folder_id: int,
        request: Request,
        body: PermanentDeleteInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.delete_folder(folder_id, body.confirmation, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/contents", status_code=201)
    def create_content(
        request: Request,
        body: ContentInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.create_content(body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/playbook/contents/{content_id}")
    def update_content(
        content_id: int,
        request: Request,
        body: ContentUpdateInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.update_content(content_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/contents/move")
    def move_contents(
        request: Request,
        body: ContentMoveInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return {"items": service.move_contents(body, context)}
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/contents/{content_id}/publish")
    def publish_content(
        content_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.set_content_status(content_id, "PUBLISHED", context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/contents/{content_id}/archive")
    def archive_content(
        content_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.set_content_status(content_id, "ARCHIVED", context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/contents/{content_id}/restore")
    def restore_content(
        content_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.set_content_status(content_id, "RESTORE", context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/contents/{content_id}/revisions")
    def revisions(
        content_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return {"items": service.revisions(content_id, context)}
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/contents/{content_id}/revisions/{revision_id}/restore")
    def restore_revision(
        content_id: int,
        revision_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.restore_revision(content_id, revision_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/playbook/contents/{content_id}/relations")
    def relations(
        content_id: int,
        request: Request,
        body: ContentRelationsInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return {"items": service.set_relations(content_id, [item.model_dump() for item in body.relations], context)}
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/contents/{content_id}/attachments/drive", status_code=201)
    def add_drive_attachment(
        content_id: int,
        request: Request,
        body: DriveAttachmentInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.add_drive_attachment(content_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/contents/{content_id}/attachments/upload", status_code=201)
    async def upload_attachment(
        content_id: int,
        request: Request,
        file: Annotated[UploadFile, File()],
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
        label: Annotated[str, Form(max_length=200)] = "",
        offline_essential: Annotated[bool, Form()] = False,
    ) -> dict[str, Any]:
        try:
            data = await file.read(max(MEDIA_LIMITS.values()) + 1)
            return service.upload_attachment(
                content_id,
                filename=file.filename or "anexo",
                label=label,
                offline_essential=offline_essential,
                data=data,
                context=context,
            )
        except Exception as exc:
            raise _handle_error(exc, request) from exc
        finally:
            await file.close()

    @router.get("/api/v1/playbook/attachments/{attachment_id}/download")
    def download_attachment(
        attachment_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_READ))],
    ) -> FileResponse:
        try:
            artifact = service.local_media(attachment_id, context)
            return FileResponse(
                artifact.path,
                media_type=artifact.media_type,
                filename=artifact.filename,
                headers={"Cache-Control": "private, max-age=0"},
            )
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/attachments/{attachment_id}/open")
    def open_drive_attachment(
        attachment_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_READ))],
    ) -> RedirectResponse:
        try:
            return RedirectResponse(service.drive_link(attachment_id, context), status_code=307)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.delete("/api/v1/playbook/attachments/{attachment_id}")
    def delete_attachment(
        attachment_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.delete_attachment(attachment_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/contents/{content_id}/favorite")
    def toggle_favorite(
        content_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_READ))],
    ) -> dict[str, bool]:
        try:
            return service.toggle_favorite(content_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/offline")
    def offline_manifest(
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_READ))],
    ) -> dict[str, Any]:
        try:
            return service.offline_manifest(context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    # PB-3B: entidades independentes do Calendário. Os endpoints de evento
    # abaixo continuam existindo como adaptadores de compatibilidade.
    @router.get("/api/v1/playbook/plans")
    def independent_plans(
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_MANAGE))],
        team_id: int | None = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        try:
            return {"items": service.list_plans(context, team_id=team_id, include_archived=include_archived)}
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/plans", status_code=201)
    def create_independent_plan(
        request: Request,
        body: IndependentPlanInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.save_independent_plan(body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/plans/{plan_id}")
    def independent_plan_detail(
        plan_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.plan_detail(plan_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/playbook/plans/{plan_id}")
    def update_independent_plan(
        plan_id: int,
        request: Request,
        body: IndependentPlanInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.save_independent_plan(body, context, plan_id=plan_id)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/plans/{plan_id}/revisions/{revision_id}/restore")
    def restore_independent_plan_revision(
        plan_id: int,
        revision_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.restore_plan_revision(plan_id, revision_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/series")
    def series(
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_MANAGE))],
        team_id: int | None = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        try:
            return {"items": service.list_series(context, team_id=team_id, include_archived=include_archived)}
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/series", status_code=201)
    def create_series(
        request: Request,
        body: PlaybookSeriesInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.save_series(body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/playbook/series/{series_id}")
    def update_series(
        series_id: int,
        request: Request,
        body: PlaybookSeriesInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.save_series(body, context, series_id=series_id)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/sessions")
    def sessions(
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_MANAGE))],
        team_id: int | None = None,
        event_id: int | None = None,
        future_only: bool = False,
    ) -> dict[str, Any]:
        try:
            return {"items": service.list_sessions(context, team_id=team_id, event_id=event_id, future_only=future_only)}
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/sessions", status_code=201)
    def create_session(
        request: Request,
        body: PlaybookSessionInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.save_session(body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/sessions/{session_id}")
    def session_detail(
        session_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.session_detail(session_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/playbook/sessions/{session_id}")
    def update_session(
        session_id: int,
        request: Request,
        body: PlaybookSessionInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.save_session(body, context, session_id=session_id)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/sessions/{session_id}/calendar-link")
    def link_session_to_calendar(
        session_id: int,
        request: Request,
        body: SessionEventLinkInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.link_session_event(session_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/sessions/{session_id}/calendar-unlink")
    def unlink_session_from_calendar(
        session_id: int,
        request: Request,
        body: SessionUnlinkInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.unlink_session_event(session_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/sessions/{session_id}/execute")
    def execute_session(
        session_id: int,
        request: Request,
        body: SessionExecutionInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.execute_session(session_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/sessions/{session_id}/evaluations")
    def evaluate_session(
        session_id: int,
        request: Request,
        body: SessionEvaluationInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return {"items": service.evaluate_session(session_id, body, context)}
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/sessions/{session_id}/revisions/{revision_id}/restore")
    def restore_session_revision(
        session_id: int,
        revision_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.restore_session_revision(session_id, revision_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/playbook/events/{event_id}/plan")
    def plan(
        event_id: int,
        request: Request,
        context: Annotated[AccessContext, Depends(require_permission(Permission.PLAYBOOK_READ))],
    ) -> dict[str, Any]:
        try:
            return service.plan(event_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/playbook/events/{event_id}/plan")
    def save_plan(
        event_id: int,
        request: Request,
        body: TrainingPlanInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.save_plan(event_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/events/{event_id}/plan/reuse")
    def reuse_plan(
        event_id: int,
        request: Request,
        body: PlanReuseInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.reuse_plan(event_id, body.source_event_id, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/playbook/events/{event_id}/finish")
    def guided_finish(
        event_id: int,
        request: Request,
        body: GuidedFinishInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.guided_finish(event_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.delete("/api/v1/playbook/contents/{content_id}")
    def delete_content(
        content_id: int,
        request: Request,
        body: PermanentDeleteInput,
        context: Annotated[AccessContext, Depends(_write_permission(Permission.PLAYBOOK_MANAGE))],
    ) -> dict[str, Any]:
        try:
            return service.delete_content(content_id, body.confirmation, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    return router
