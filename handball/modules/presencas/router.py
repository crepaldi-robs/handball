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

from .domain import history_to_dataframe
from .schemas import MemberCreate, MemberUpdate, SessionNotes, SyncBatch
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
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/app/presencas", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "presencas/index.html",
            {"username": session.username},
        )

    @router.get("/api/v1/auth/session")
    def auth_session(
        session: AuthSession = Depends(require_session),
    ) -> dict[str, str]:
        return {"username": session.username, "csrf_token": session.csrf_token}

    @router.get("/api/v1/session")
    def get_session(
        training_date: str,
        _: AuthSession = Depends(require_session),
    ) -> dict[str, Any]:
        return service.session_payload(_parse_date(training_date))

    @router.put("/api/v1/sessions/{session_id}/records")
    def sync_session_records(
        session_id: int,
        batch: SyncBatch,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        try:
            results = service.sync_records(
                session_id,
                [item.model_dump() for item in batch.operations],
                offline=batch.offline,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"results": results}

    @router.post("/api/v1/sessions/{session_id}/finalize")
    def finalize_session(
        session_id: int,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        return service.finalize_session(session_id)

    @router.post("/api/v1/sessions/{session_id}/reopen")
    def reopen_session(
        session_id: int,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        return service.reopen_session(session_id)

    @router.put("/api/v1/sessions/{session_id}/notes")
    def update_session_notes(
        session_id: int,
        body: SessionNotes,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        return service.update_session_notes(session_id, body.notes)

    @router.get("/api/v1/history")
    def history(_: AuthSession = Depends(require_session)) -> dict[str, Any]:
        return {"items": service.history()}

    @router.get("/api/v1/audit")
    def audit(
        limit: int = 500,
        _: AuthSession = Depends(require_session),
    ) -> dict[str, Any]:
        return {"items": service.audit(limit=min(max(limit, 1), 1000))}

    @router.get("/api/v1/members")
    def members(_: AuthSession = Depends(require_session)) -> dict[str, Any]:
        return {"items": service.members()}

    @router.post("/api/v1/members")
    def add_member(
        body: MemberCreate,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        try:
            return {"items": service.add_member(body.name, body.position)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/v1/members/{member_id}")
    def update_member(
        member_id: int,
        body: MemberUpdate,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        try:
            return {
                "items": service.update_member(
                    member_id,
                    position=body.position,
                    active=body.active,
                )
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/v1/exports/session/{session_id}.csv")
    def export_session(
        session_id: int,
        _: AuthSession = Depends(require_session),
    ) -> StreamingResponse:
        training, rows = service.session_export_rows(session_id)
        return _csv_response(
            history_to_dataframe(rows),
            f"presencas_{training['training_date']}.csv",
        )

    @router.get("/api/v1/exports/history.csv")
    def export_history(
        _: AuthSession = Depends(require_session),
    ) -> StreamingResponse:
        return _csv_response(
            history_to_dataframe(service.history()),
            "historico_completo_presencas.csv",
        )

    @router.get("/api/v1/backup")
    def download_backup(
        _: AuthSession = Depends(require_session),
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
