from __future__ import annotations

from typing import Annotated, Any, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from handball.core.auth import require_write_session, session_from_request
from handball.core.authorization import (
    AccessContext,
    Permission,
    require_permission,
)
from handball.core.errors import CalendarProblem
from handball.modules.usuarios.service import IdentityService

from .schemas import (
    CalendarActionInput,
    CalendarConflictCheckInput,
    CalendarEventInput,
    CalendarJustificationInput,
    CalendarRescheduleInput,
    CalendarSeriesEditInput,
    CalendarSeriesInput,
    CalendarVisibilityInput,
)
from .service import ACTIVE_SEASON_LABEL, CalendarService


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
    if isinstance(exc, CalendarProblem):
        return HTTPException(
            status_code=exc.status_code,
            detail=exc.to_detail(request_id=request_id),
        )
    if isinstance(exc, PermissionError):
        problem = CalendarProblem(
            code="calendar.permission_denied",
            title="Esta ação não está disponível para sua conta",
            message=str(exc) or "Sua conta não possui esta permissão.",
            suggestion="Volte ao calendário ou peça ajuda ao responsável pelo time.",
            status_code=403,
        )
        return HTTPException(
            status_code=403,
            detail=problem.to_detail(request_id=request_id),
        )
    if isinstance(exc, KeyError):
        problem = CalendarProblem(
            code="calendar.not_found",
            title="Evento não encontrado",
            message=str(exc).strip("'"),
            suggestion="Recarregue o calendário e tente novamente.",
            status_code=404,
        )
        return HTTPException(
            status_code=404,
            detail=problem.to_detail(request_id=request_id),
        )
    if isinstance(exc, ValueError):
        problem = CalendarProblem(
            code="calendar.invalid_request",
            title="Não foi possível concluir a ação",
            message=str(exc),
            suggestion="Confira os campos destacados e tente novamente.",
            status_code=400,
        )
        return HTTPException(
            status_code=400,
            detail=problem.to_detail(request_id=request_id),
        )
    problem = CalendarProblem(
        code="calendar.unexpected",
        title="Algo inesperado aconteceu",
        message="O calendário não conseguiu concluir esta ação.",
        suggestion="Tente novamente. Se continuar, informe o código de suporte.",
        status_code=500,
    )
    return HTTPException(
        status_code=500,
        detail=problem.to_detail(request_id=request_id),
    )


def create_router(
    service: CalendarService,
    identity_service: IdentityService,
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
        team_view = identity_service.resolve_active_team_view(session.to_access_context())
        return templates.TemplateResponse(
            request,
            "calendario/index.html",
            {
                "session": session,
                "organization": team_view["organization"],
                "team_theme": team_view["team_theme"],
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
        request: Request,
        context: Annotated[
            AccessContext,
            Depends(require_permission(Permission.CALENDAR_READ_TEAM)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.options(context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/calendar")
    def calendar(
        request: Request,
        context: Annotated[
            AccessContext,
            Depends(require_permission(Permission.CALENDAR_READ_TEAM)),
        ],
        team_id: int | None = None,
        season_id: int | None = None,
        season_label: str | None = None,
        starts_from: str | None = None,
        ends_to: str | None = None,
        event_type: Annotated[list[str] | None, Query()] = None,
        status: Annotated[list[str] | None, Query()] = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
    ) -> dict[str, Any]:
        try:
            return service.calendar(
                context,
                team_id=team_id,
                season_id=season_id,
                season_label=season_label,
                starts_from=starts_from,
                ends_to=ends_to,
                event_types=event_type or (),
                statuses=status or (),
                query=q,
            )
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/calendar/events", status_code=201)
    def create_event(
        request: Request,
        body: CalendarEventInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", max_length=128),
        ] = None,
    ) -> dict[str, Any]:
        try:
            return service.create_event(
                body,
                context,
                operation_id=(idempotency_key or "").strip() or None,
            )
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/calendar/events/{event_id}")
    def update_event(
        event_id: int,
        request: Request,
        body: CalendarEventInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.update_event(event_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/calendar/events/{event_id}/player-visibility")
    def set_player_visibility(
        event_id: int,
        request: Request,
        body: CalendarVisibilityInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_VISIBILITY_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.set_player_visibility(event_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/calendar/events/check")
    def check_conflicts(
        request: Request,
        body: CalendarConflictCheckInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.check_conflicts(body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/calendar/events/{event_id}/confirm")
    def confirm_event(
        event_id: int,
        request: Request,
        body: CalendarActionInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.transition_event(event_id, "CONFIRM", body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/calendar/events/{event_id}/complete")
    def complete_event(
        event_id: int,
        request: Request,
        body: CalendarActionInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.transition_event(event_id, "COMPLETE", body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/calendar/events/{event_id}/cancel")
    def cancel_event(
        event_id: int,
        request: Request,
        body: CalendarActionInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.transition_event(event_id, "CANCEL", body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/calendar/events/{event_id}/undo-cancel")
    def undo_cancel_event(
        event_id: int,
        request: Request,
        body: CalendarActionInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.transition_event(event_id, "UNDO_CANCEL", body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/calendar/events/{event_id}/reschedule")
    def reschedule_event(
        event_id: int,
        request: Request,
        body: CalendarRescheduleInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.reschedule_event(event_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.get("/api/v1/calendar/events/{event_id}/history")
    def event_history(
        event_id: int,
        request: Request,
        context: Annotated[
            AccessContext,
            Depends(require_permission(Permission.CALENDAR_READ_TEAM)),
        ],
    ) -> dict[str, Any]:
        try:
            return {"items": service.event_history(event_id, context)}
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/calendar/series/preview")
    def preview_series(
        request: Request,
        body: CalendarSeriesInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.preview_series(body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/calendar/series", status_code=201)
    def create_series(
        request: Request,
        body: CalendarSeriesInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.create_series(body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/calendar/series/{series_id}")
    def update_series(
        series_id: int,
        request: Request,
        body: CalendarSeriesEditInput,
        context: Annotated[
            AccessContext,
            Depends(_write_permission(Permission.CALENDAR_MANAGE)),
        ],
    ) -> dict[str, Any]:
        try:
            return service.update_series(series_id, body, context)
        except Exception as exc:
            raise _handle_error(exc, request) from exc

    @router.post("/api/v1/calendar/events/{event_id}/justification")
    def create_justification(
        event_id: int,
        request: Request,
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
            raise _handle_error(exc, request) from exc

    @router.put("/api/v1/calendar/justifications/{justification_id}")
    def update_justification(
        justification_id: int,
        request: Request,
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
            raise _handle_error(exc, request) from exc

    return router
