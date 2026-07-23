from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from handball.core.auth import session_from_request
from handball.core.authorization import Permission

from .service import StatisticsService


def create_router(
    service: StatisticsService,
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/app/estatisticas", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if Permission.ATTENDANCE_READ_TEAM not in session.permissions:
            raise HTTPException(status_code=403)
        return templates.TemplateResponse(
            request,
            "estatisticas/index.html",
            {
                "username": session.username,
                "csrf_token": session.csrf_token,
                "module": service.status().model_dump(),
            },
        )

    return router
