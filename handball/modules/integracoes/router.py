from __future__ import annotations

from typing import Annotated, Any, Callable
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from handball.core.auth import require_write_session, session_from_request
from handball.core.authorization import AccessContext, Permission, require_permission
from handball.core.config import AppSettings
from handball.integrations.google import GoogleIntegrationError
from handball.modules.usuarios.service import IdentityService

from .schemas import GoogleCalendarSettingsInput, GoogleDisconnectInput, GoogleTeamInput
from .service import GoogleIntegrationService


OAUTH_COOKIE = "handball_google_oauth"


def _write_permission() -> Callable[[Request], AccessContext]:
    permission_dependency = require_permission(Permission.INTEGRATIONS_GOOGLE_MANAGE)

    def dependency(request: Request) -> AccessContext:
        context = permission_dependency(request)
        require_write_session(request)
        return context

    return dependency


def _problem(exc: Exception, request: Request | None = None) -> HTTPException:
    request_id = (
        request.headers.get("X-Request-ID") if request is not None else None
    ) or uuid4().hex[:12]
    status_code = 500
    code = "google.unexpected"
    title = "Não foi possível concluir esta etapa"
    message = "A integração Google encontrou um problema inesperado."
    suggestion = "Tente de novo. Se continuar, informe o código de suporte."
    if isinstance(exc, GoogleIntegrationError):
        status_code = 503 if exc.retryable else 400
        code = exc.code
        message = str(exc)
        suggestion = (
            "Aguarde alguns instantes e tente novamente."
            if exc.retryable
            else "Leia a ajuda desta etapa e tente novamente."
        )
    elif isinstance(exc, PermissionError):
        status_code = 403
        code = "google.permission_denied"
        title = "Esta área é exclusiva da comissão técnica"
        message = str(exc) or "Sua conta não possui esta permissão."
        suggestion = "Entre com uma conta da CT responsável por este time."
    elif isinstance(exc, (KeyError, ValueError)):
        status_code = 400
        code = "google.invalid_request"
        message = str(exc).strip("'")
        suggestion = "Recarregue a página, confira a etapa e tente novamente."
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "title": title,
            "message": message,
            "suggestion": suggestion,
            "recoverable": status_code < 500 or isinstance(exc, GoogleIntegrationError),
            "request_id": request_id,
        },
    )


def create_router(
    service: GoogleIntegrationService,
    identity_service: IdentityService,
    templates: Jinja2Templates,
    settings: AppSettings,
) -> APIRouter:
    router = APIRouter()

    @router.get("/google-integration", response_class=HTMLResponse)
    def public_information(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "integracoes/google-public.html",
            {
                "privacy_url": "/privacy/google-integration",
                "terms_url": "/terms/google-integration",
            },
        )

    @router.get("/privacy/google-integration", response_class=HTMLResponse)
    def privacy(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "integracoes/google-privacy.html",
            {},
        )

    @router.get("/terms/google-integration", response_class=HTMLResponse)
    def terms(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "integracoes/google-terms.html",
            {},
        )

    @router.get("/app/integracoes/google", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if Permission.INTEGRATIONS_GOOGLE_MANAGE not in session.permissions:
            raise HTTPException(status_code=403)
        context = session.to_access_context()
        team_view = identity_service.resolve_active_team_view(context)
        selected_team_id = min(context.team_ids) if context.team_ids else None
        return templates.TemplateResponse(
            request,
            "integracoes/google.html",
            {
                "session": session,
                "organization": team_view["organization"],
                "team_theme": team_view["team_theme"],
                "selected_team_id": selected_team_id,
            },
        )

    @router.get("/api/v1/integrations/google")
    def status(
        request: Request,
        context: Annotated[
            AccessContext,
            Depends(require_permission(Permission.INTEGRATIONS_GOOGLE_MANAGE)),
        ],
        team_id: int | None = None,
    ) -> dict[str, Any]:
        try:
            return service.status(context, team_id=team_id)
        except Exception as exc:
            raise _problem(exc, request) from exc

    @router.post("/api/v1/integrations/google/oauth/start")
    def oauth_start(
        request: Request,
        body: GoogleTeamInput,
        context: Annotated[AccessContext, Depends(_write_permission())],
    ) -> Response:
        try:
            result = service.begin_oauth(context, team_id=body.team_id)
        except Exception as exc:
            raise _problem(exc, request) from exc
        response = JSONResponse({"authorization_url": result["authorization_url"]})
        response.set_cookie(
            OAUTH_COOKIE,
            result["state_cookie"],
            max_age=600,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/api/v1/integrations/google/oauth/callback",
        )
        return response

    @router.get("/api/v1/integrations/google/oauth/callback")
    def oauth_callback(
        request: Request,
        code: Annotated[str | None, Query(max_length=4096)] = None,
        state: Annotated[str | None, Query(max_length=2048)] = None,
        error: Annotated[str | None, Query(max_length=200)] = None,
        state_cookie: Annotated[str | None, Cookie(alias=OAUTH_COOKIE)] = None,
    ) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        query: dict[str, str]
        if error:
            query = {"google": "cancelled"}
        elif not code or not state or not state_cookie:
            query = {"google": "invalid"}
        else:
            try:
                service.finish_oauth(
                    session.to_access_context(),
                    code=code,
                    state=state,
                    state_cookie=state_cookie,
                )
                query = {"google": "connected"}
            except Exception as exc:
                problem = _problem(exc, request).detail
                query = {
                    "google": "error",
                    "code": str(problem.get("code") or "google.unexpected")[:100],
                }
        response = RedirectResponse(
            "/app/integracoes/google?" + urlencode(query),
            status_code=303,
        )
        response.delete_cookie(
            OAUTH_COOKIE,
            path="/api/v1/integrations/google/oauth/callback",
        )
        return response

    @router.post("/api/v1/integrations/google/calendar/setup")
    def setup_calendar(
        request: Request,
        body: GoogleTeamInput,
        context: Annotated[AccessContext, Depends(_write_permission())],
    ) -> dict[str, Any]:
        try:
            return service.setup_calendar(context, team_id=body.team_id)
        except Exception as exc:
            raise _problem(exc, request) from exc

    @router.put("/api/v1/integrations/google/calendar/settings")
    def update_settings(
        request: Request,
        body: GoogleCalendarSettingsInput,
        context: Annotated[AccessContext, Depends(_write_permission())],
    ) -> dict[str, Any]:
        try:
            payload = body.model_dump(exclude={"team_id"})
            return service.update_settings(
                context,
                payload,
                team_id=body.team_id,
            )
        except Exception as exc:
            raise _problem(exc, request) from exc

    @router.post("/api/v1/integrations/google/calendar/sync")
    def sync_now(
        request: Request,
        body: GoogleTeamInput,
        context: Annotated[AccessContext, Depends(_write_permission())],
    ) -> dict[str, Any]:
        try:
            return service.sync_now(context, team_id=body.team_id)
        except Exception as exc:
            raise _problem(exc, request) from exc

    @router.post("/api/v1/integrations/google/pause")
    def pause(
        request: Request,
        body: GoogleTeamInput,
        context: Annotated[AccessContext, Depends(_write_permission())],
    ) -> dict[str, Any]:
        try:
            return service.pause(context, team_id=body.team_id)
        except Exception as exc:
            raise _problem(exc, request) from exc

    @router.post("/api/v1/integrations/google/resume")
    def resume(
        request: Request,
        body: GoogleTeamInput,
        context: Annotated[AccessContext, Depends(_write_permission())],
    ) -> dict[str, Any]:
        try:
            return service.resume(context, team_id=body.team_id)
        except Exception as exc:
            raise _problem(exc, request) from exc

    @router.post("/api/v1/integrations/google/disconnect")
    def disconnect(
        request: Request,
        body: GoogleDisconnectInput,
        context: Annotated[AccessContext, Depends(_write_permission())],
    ) -> dict[str, Any]:
        try:
            return service.disconnect(
                context,
                team_id=body.team_id,
                connection_version=body.connection_version,
                make_calendar_private=body.make_calendar_private,
            )
        except Exception as exc:
            raise _problem(exc, request) from exc

    return router
