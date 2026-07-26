from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from handball.core.auth import require_write_session, session_from_request
from handball.core.authorization import (
    AccessContext,
    Permission,
    require_permission,
)
from handball.core.organization import ORGANIZATION

from .schemas import CalendarEventInput, CalendarJustificationInput
from .service import ACTIVE_SEASON_LABEL, CalendarService


def _write_permission(permission: Permission) -> Callable[[Request], AccessContext]:
    permission_dependency = require_permission(permission)

    def dependency(request: Request) -> AccessContext:
        context = permission_dependency(request)
        require_write_session(request)
        return context

    return dependency


def _handle_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc).strip("'"))
    return HTTPException(status_code=400, detail=str(exc))


def create_router(
    service: CalendarService,
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/app/calendario", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if Permission.CALENDAR_READ_TEAM not in session.permissions:
            raise HTTPException(status_code=403)
        return templates.TemplateResponse(
            request,
            "calendario/index.html",
            {
                "session": session,
                "organization": ORGANIZATION,
                "active_season_label": ACTIVE_SEASON_LABEL,
                "can_manage": Permission.CALENDAR_MANAGE in session.permissions,
                "can_justify": (
                    Permission.CALENDAR_JUSTIFICATION_SELF
                    in session.permissions
                ),
            },
        )

    @router.get("/api/v1/calendar/options")
    def options(
        context: Annotated[
            AccessContext,
            Depends(require_permission(Permission.CALENDAR_READ_TEAM)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.options(context)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/api/v1/calendar")
    def calendar(
        context: Annotated[
            AccessContext,
            Depends(require_permission(Permission.CALENDAR_READ_TEAM)),
        ],
        team_id: int | None = None,
        season_id: int | None = None,
        season_label: str | None = None,
    ) -> dict[str, Any]:
        try:
            return service.calendar(
                context,
                team_id=team_id,
                season_id=season_id,
                season_label=season_label,
            )
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.post("/api/v1/calendar/events", status_code=201)
    def create_event(
        body: CalendarEventInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.create_event(body, context)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.put("/api/v1/calendar/events/{event_id}")
    def update_event(
        event_id: int,
        body: CalendarEventInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.update_event(event_id, body, context)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.post("/api/v1/calendar/events/{event_id}/justification")
    def create_justification(
        event_id: int,
        body: CalendarJustificationInput,
        context: Annotated[
            AccessContext,
            Depends(
                _write_permission(Permission.CALENDAR_JUSTIFICATION_SELF)
            ),
        ],
    ) -> dict[str, Any]:
        try:
            return service.save_own_justification(event_id, body.reason, context)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.put("/api/v1/calendar/justifications/{justification_id}")
    def update_justification(
        justification_id: int,
        body: CalendarJustificationInput,
        context: Annotated[
            AccessContext,
            Depends(
                _write_permission(Permission.CALENDAR_JUSTIFICATION_SELF)
            ),
        ],
    ) -> dict[str, Any]:
        try:
            return service.update_own_justification(
                justification_id,
                body.reason,
                context,
            )
        except Exception as exc:
            raise _handle_error(exc) from exc

    return router
