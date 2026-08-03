from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from handball.core.auth import session_from_request
from handball.core.authorization import AccessContext, Permission, require_read_only_permission
from handball.modules.usuarios.service import IdentityService

from .schemas import SqlChangeExecuteInput, SqlChangeInput, SqlQueryInput
from .service import SqlChangeConflict, SqlExplorerService


def _error(exc: Exception) -> HTTPException:
    status_code = 408 if isinstance(exc, TimeoutError) else 400
    if isinstance(exc, PermissionError):
        status_code = 403
    if isinstance(exc, SqlChangeConflict):
        status_code = 409
    if isinstance(exc, RuntimeError) and not isinstance(exc, SqlChangeConflict):
        status_code = 503
    return HTTPException(status_code=status_code, detail=str(exc))


def _delete(path: Path) -> None:
    path.unlink(missing_ok=True)


def _admin_write_context(request: Request) -> AccessContext:
    session = session_from_request(request, touch=False)
    if session is None:
        raise HTTPException(status_code=401)
    if Permission.SQL_ADMIN not in session.permissions:
        raise HTTPException(status_code=403)
    supplied = request.headers.get("X-CSRF-Token", "")
    if not secrets.compare_digest(supplied, session.csrf_token):
        raise HTTPException(status_code=403, detail="Token CSRF inválido.")
    return session.to_access_context()


def create_router(service: SqlExplorerService, identity_service: IdentityService, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()
    @router.get("/app/consultas", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_from_request(request, touch=False)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if Permission.SQL_EXPLORE not in session.permissions and Permission.SQL_ADMIN not in session.permissions:
            raise HTTPException(status_code=403)
        team_view = identity_service.resolve_active_team_view(session.to_access_context())
        return templates.TemplateResponse(
            request,
            "consultas/index.html",
            {
                "session": session,
                "can_write": Permission.SQL_ADMIN in session.permissions,
                "organization": team_view["organization"],
                "team_theme": team_view["team_theme"],
            },
        )

    @router.get("/api/v1/sql/catalog")
    def catalog(
        context: Annotated[
            AccessContext,
            Depends(require_read_only_permission(Permission.SQL_EXPLORE, Permission.SQL_ADMIN)),
        ],
    ) -> dict:
        try:
            return service.catalog(context)
        except Exception as exc:
            raise _error(exc) from exc

    @router.post("/api/v1/sql/query")
    def query(
        body: SqlQueryInput,
        context: Annotated[
            AccessContext,
            Depends(require_read_only_permission(Permission.SQL_EXPLORE, Permission.SQL_ADMIN)),
        ],
    ) -> dict:
        try:
            return service.query(context, sql=body.sql, page=body.page, page_size=body.page_size)
        except Exception as exc:
            raise _error(exc) from exc

    @router.post("/api/v1/sql/changes/preview")
    def preview_change(
        body: SqlChangeInput,
        context: Annotated[AccessContext, Depends(_admin_write_context)],
    ) -> dict:
        try:
            return service.preview_change(context, sql=body.sql)
        except Exception as exc:
            raise _error(exc) from exc

    @router.post("/api/v1/sql/changes/execute")
    def execute_change(
        body: SqlChangeExecuteInput,
        context: Annotated[AccessContext, Depends(_admin_write_context)],
    ) -> dict:
        try:
            return service.execute_change(context, token=body.token)
        except Exception as exc:
            raise _error(exc) from exc

    @router.post("/api/v1/sql/explain")
    def explain(
        body: SqlQueryInput,
        context: Annotated[
            AccessContext,
            Depends(require_read_only_permission(Permission.SQL_EXPLORE, Permission.SQL_ADMIN)),
        ],
    ) -> dict:
        try:
            return {"items": service.explain(context, sql=body.sql)}
        except Exception as exc:
            raise _error(exc) from exc

    @router.post("/api/v1/sql/export/{format}")
    def export(
        format: str,
        body: SqlQueryInput,
        background_tasks: BackgroundTasks,
        context: Annotated[
            AccessContext,
            Depends(require_read_only_permission(Permission.SQL_EXPLORE, Permission.SQL_ADMIN)),
        ],
    ) -> FileResponse:
        try:
            path = service.export(context, sql=body.sql, format=format)
        except Exception as exc:
            raise _error(exc) from exc
        background_tasks.add_task(_delete, path)
        media_type = "text/csv" if format == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return FileResponse(path, media_type=media_type, filename=f"consulta.{format}", background=background_tasks)

    return router
