from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from handball.core.auth import session_from_request
from handball.core.authorization import Permission
from handball.modules.usuarios.service import IdentityService


def create_router(identity_service: IdentityService, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/app", response_class=HTMLResponse)
    def hub(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        team_view = identity_service.resolve_active_team_view(session.to_access_context())
        return templates.TemplateResponse(
            request,
            "hub.html",
            {
                "username": session.username,
                "display_name": session.display_name,
                "csrf_token": session.csrf_token,
                "roles": sorted(session.system_roles | session.team_roles),
                "can_attendance": Permission.ATTENDANCE_READ_TEAM in session.permissions,
                "can_self_attendance": Permission.ATTENDANCE_READ_SELF in session.permissions,
                "can_report": Permission.REPORTS_READ_SELF in session.permissions,
                "can_admin": Permission.USERS_MANAGE in session.permissions,
                "can_calendar": Permission.CALENDAR_READ_TEAM in session.permissions,
                "can_playbook": Permission.PLAYBOOK_READ in session.permissions,
                "can_sql_explorer": Permission.SQL_EXPLORE in session.permissions or Permission.SQL_ADMIN in session.permissions,
                "organization": team_view["organization"],
                "team_theme": team_view["team_theme"],
            },
        )

    return router
