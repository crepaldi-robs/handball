from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from handball.core.auth import session_from_request
from handball.core.authorization import AccessContext, Permission, require_read_only_permission

from .schemas import SqlQueryInput
from .service import SqlExplorerService


def _error(exc: Exception) -> HTTPException:
    status_code = 408 if isinstance(exc, TimeoutError) else 400
    if isinstance(exc, PermissionError):
        status_code = 403
    return HTTPException(status_code=status_code, detail=str(exc))


def _delete(path: Path) -> None:
    path.unlink(missing_ok=True)


def create_router(service: SqlExplorerService, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()
    @router.get("/app/consultas", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_from_request(request, touch=False)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if Permission.SQL_EXPLORE not in session.permissions:
            raise HTTPException(status_code=403)
        return templates.TemplateResponse(
            request,
            "consultas/index.html",
            {"session": session},
        )

    @router.get("/api/v1/sql/catalog")
    def catalog(
        context: Annotated[
            AccessContext,
            Depends(require_read_only_permission(Permission.SQL_EXPLORE)),
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
            Depends(require_read_only_permission(Permission.SQL_EXPLORE)),
        ],
    ) -> dict:
        try:
            return service.preview(context, sql=body.sql, page=body.page, page_size=body.page_size)
        except Exception as exc:
            raise _error(exc) from exc

    @router.post("/api/v1/sql/explain")
    def explain(
        body: SqlQueryInput,
        context: Annotated[
            AccessContext,
            Depends(require_read_only_permission(Permission.SQL_EXPLORE)),
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
            Depends(require_read_only_permission(Permission.SQL_EXPLORE)),
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
