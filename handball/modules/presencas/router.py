from __future__ import annotations

import io
from datetime import date
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates

from handball.core.auth import (
    AuthSession,
    require_session,
    require_write_session,
    session_from_request,
)
from handball.core.authorization import AccessContext, Permission, require_permission
from handball.modules.usuarios.service import IdentityService

from .domain import history_to_dataframe
from .schemas import MemberCreate, MemberUpdate, SelfConfirmationInput, SessionNotes, SyncBatch
from .service import AttendanceService


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Data inválida.") from exc


def _csv_response(dataframe: pd.DataFrame, filename: str) -> StreamingResponse:
    content = "\ufeff" + dataframe.to_csv(index=False)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def create_router(
    service: AttendanceService,
    identity_service: IdentityService,
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/app/presencas", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if Permission.ATTENDANCE_READ_TEAM not in session.permissions and Permission.ATTENDANCE_READ_SELF not in session.permissions:
            raise HTTPException(status_code=403)
        team_view = identity_service.resolve_active_team_view(session.to_access_context())
        if Permission.ATTENDANCE_READ_TEAM not in session.permissions:
            return templates.TemplateResponse(
                request,
                "presencas/player.html",
                {"session": session, "organization": team_view["organization"], "team_theme": team_view["team_theme"]},
            )
        return templates.TemplateResponse(
            request,
            "presencas/index.html",
            {
                "username": session.username,
                "session": session,
                "organization": team_view["organization"],
                "team_theme": team_view["team_theme"],
            },
        )

    @router.get("/api/v1/auth/session")
    def auth_session(
        session: AuthSession = Depends(require_session),
    ) -> dict[str, Any]:
        return {
            "user_id": session.user_id,
            "username": session.username,
            "display_name": session.display_name,
            "csrf_token": session.csrf_token,
            "roles": sorted(session.system_roles | session.team_roles),
            "permissions": sorted(str(value) for value in session.permissions),
            "team_ids": sorted(session.team_ids),
            "linked_player_id": session.linked_player_id,
        }

    @router.post("/api/v1/me/attendance/active")
    def active_self_confirmation(context: AuthSession = Depends(require_write_session)) -> dict[str, Any]:
        if Permission.ATTENDANCE_WRITE_SELF not in context.permissions or context.linked_player_id is None:
            raise HTTPException(status_code=403)
        try:
            payload = service.active_self_confirmation(
                team_ids=context.team_ids, player_member_id=context.linked_player_id, actor_user_id=context.user_id
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"item": payload}

    @router.put("/api/v1/me/attendance/events/{event_id}")
    def save_self_confirmation(
        event_id: int, body: SelfConfirmationInput, context: AuthSession = Depends(require_write_session)
    ) -> dict[str, Any]:
        if Permission.ATTENDANCE_WRITE_SELF not in context.permissions or context.linked_player_id is None:
            raise HTTPException(status_code=403)
        try:
            return service.save_self_confirmation(
                event_id, response=body.response, positions=body.positions, justification=body.justification,
                base_version=body.base_version, team_ids=context.team_ids,
                player_member_id=context.linked_player_id, actor_user_id=context.user_id,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/api/v1/session")
    def get_session(
        training_date: str,
        context: AccessContext = Depends(require_permission(Permission.ATTENDANCE_READ_TEAM)),
    ) -> dict[str, Any]:
        del training_date, context
        raise HTTPException(
            status_code=410,
            detail="A chamada agora deve ser aberta a partir de um treino do calendário.",
        )

    @router.get("/api/v1/attendance/trainings")
    def calendar_trainings(
        season_id: int | None = None,
        context: AccessContext = Depends(
            require_permission(Permission.ATTENDANCE_READ_TEAM)
        ),
    ) -> dict[str, Any]:
        return {
            "items": service.calendar_trainings(
                team_ids=context.team_ids,
                season_id=season_id,
            )
        }

    @router.post("/api/v1/attendance/trainings/{event_id}/session")
    def open_calendar_training(
        event_id: int,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        if Permission.ATTENDANCE_WRITE not in context.permissions:
            raise HTTPException(status_code=403)
        try:
            return service.open_calendar_training(
                event_id,
                team_ids=context.team_ids,
                actor_user_id=context.user_id or 0,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/api/v1/sessions/{session_id}")
    def calendar_session(
        session_id: int,
        context: AccessContext = Depends(
            require_permission(Permission.ATTENDANCE_READ_TEAM)
        ),
    ) -> dict[str, Any]:
        try:
            return service.calendar_session_payload(
                session_id,
                team_ids=context.team_ids,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.put("/api/v1/sessions/{session_id}/records")
    def sync_session_records(
        session_id: int,
        batch: SyncBatch,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        if Permission.ATTENDANCE_WRITE not in context.permissions:
            raise HTTPException(status_code=403)
        if batch.offline and any(
            item.creator_user_id != context.user_id for item in batch.operations
        ):
            raise HTTPException(status_code=403, detail="Fila offline pertence a outro usuário.")
        try:
            results = service.sync_records(
                session_id,
                [item.model_dump() for item in batch.operations],
                offline=batch.offline,
                actor_user_id=context.user_id or None,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"results": results}

    @router.post("/api/v1/sessions/{session_id}/finalize")
    def finalize_session(
        session_id: int,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        if Permission.ATTENDANCE_FINALIZE not in context.permissions:
            raise HTTPException(status_code=403)
        return service.finalize_session(session_id, actor_user_id=context.user_id or None)

    @router.post("/api/v1/sessions/{session_id}/reopen")
    def reopen_session(
        session_id: int,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        if Permission.ATTENDANCE_REOPEN not in context.permissions:
            raise HTTPException(status_code=403)
        return service.reopen_session(session_id, actor_user_id=context.user_id or None)

    @router.put("/api/v1/sessions/{session_id}/notes")
    def update_session_notes(
        session_id: int,
        body: SessionNotes,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        if Permission.ATTENDANCE_WRITE not in context.permissions:
            raise HTTPException(status_code=403)
        return service.update_session_notes(session_id, body.notes, actor_user_id=context.user_id or None)

    @router.get("/api/v1/history")
    def history(_: AccessContext = Depends(require_permission(Permission.ATTENDANCE_READ_TEAM))) -> dict[str, Any]:
        return {"items": service.history()}

    @router.get("/api/v1/audit")
    def audit(
        limit: int = 500,
        _: AccessContext = Depends(require_permission(Permission.AUDIT_READ_SPORT)),
    ) -> dict[str, Any]:
        return {"items": service.audit(limit=min(max(limit, 1), 1000))}

    @router.get("/api/v1/members")
    def members(_: AccessContext = Depends(require_permission(Permission.MEMBERS_READ_TEAM))) -> dict[str, Any]:
        return {"items": service.members()}

    @router.post("/api/v1/members")
    def add_member(
        body: MemberCreate,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        try:
            if Permission.MEMBERS_MANAGE not in context.permissions:
                raise HTTPException(status_code=403)
            return {"items": service.add_member(body.name, body.position, actor_user_id=context.user_id or None)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/v1/members/{member_id}")
    def update_member(
        member_id: int,
        body: MemberUpdate,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        try:
            if Permission.MEMBERS_MANAGE not in context.permissions:
                raise HTTPException(status_code=403)
            return {
                "items": service.update_member(
                    member_id,
                    position=body.position,
                    active=body.active,
                    actor_user_id=context.user_id or None,
                )
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/v1/exports/session/{session_id}.csv")
    def export_session(
        session_id: int,
        _: AccessContext = Depends(require_permission(Permission.EXPORT_READ_TEAM)),
    ) -> StreamingResponse:
        training, rows = service.session_export_rows(session_id)
        return _csv_response(
            history_to_dataframe(rows),
            f"presencas_{training['training_date']}.csv",
        )

    @router.get("/api/v1/exports/history.csv")
    def export_history(
        _: AccessContext = Depends(require_permission(Permission.EXPORT_READ_TEAM)),
    ) -> StreamingResponse:
        return _csv_response(
            history_to_dataframe(service.history()),
            "historico_completo_presencas.csv",
        )

    @router.get("/api/v1/backup")
    def download_backup(
        _: AccessContext = Depends(require_permission(Permission.BACKUP_DOWNLOAD)),
    ) -> StreamingResponse:
        artifact = service.create_backup_download()
        return StreamingResponse(
            artifact.iter_bytes(),
            media_type=artifact.media_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{artifact.filename}"'
                ),
                "Content-Length": str(artifact.content_length),
            },
        )

    return router
