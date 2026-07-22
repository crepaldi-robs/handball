from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from handball.core.auth import session_from_request


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
            {"username": session.username},
        )

    return router
