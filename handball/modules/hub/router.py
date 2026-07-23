from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from handball.core.auth import session_from_request
from handball.core.authorization import Permission
from handball.core.organization import ORGANIZATION


def create_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/app", response_class=HTMLResponse)
    def hub(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "hub.html",
            {
                "username": session.username,
                "display_name": session.display_name,
                "csrf_token": session.csrf_token,
                "roles": sorted(session.system_roles | session.team_roles),
                "can_attendance": Permission.ATTENDANCE_READ_TEAM in session.permissions,
                "can_report": Permission.REPORTS_READ_SELF in session.permissions,
                "can_admin": Permission.USERS_MANAGE in session.permissions,
                "organization": ORGANIZATION,
            },
        )

    return router
