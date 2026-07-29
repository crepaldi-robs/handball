from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from handball.core.auth import require_write_session, session_from_request
from handball.core.authorization import AccessContext, Permission, require_authenticated_user, require_permission
from handball.core.organization import ORGANIZATION

from .schemas import OwnPasswordChange, PermissionGrantUpdate, RoleUpdate, TemporaryPasswordReset, UserCreate
from .service import IdentityService


def _write_permission(permission: Permission):
    permission_dependency = require_permission(permission)

    def dependency(request: Request) -> AccessContext:
        context = permission_dependency(request)
        require_write_session(request)
        return context

    return dependency


def create_router(service: IdentityService, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/app/meu-relatorio", response_class=HTMLResponse)
    def report_page(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if Permission.REPORTS_READ_SELF not in session.permissions:
            raise HTTPException(status_code=403)
        return templates.TemplateResponse(
            request,
            "usuarios/report.html",
            {"session": session, "report": service.own_report(session.to_access_context()), "organization": ORGANIZATION},
        )

    @router.get("/app/admin/usuarios", response_class=HTMLResponse)
    def admin_page(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if Permission.USERS_MANAGE not in session.permissions:
            raise HTTPException(status_code=403)
        return templates.TemplateResponse(
            request,
            "usuarios/admin.html",
            {"session": session, "users": service.list_users(), "options": service.options(), "organization": ORGANIZATION},
        )

    @router.get("/api/v1/me")
    def me(context: Annotated[AccessContext, Depends(require_authenticated_user)]) -> dict[str, Any]:
        return service.me(context)

    @router.get("/api/v1/me/attendance")
    def own_attendance(context: Annotated[AccessContext, Depends(require_permission(Permission.ATTENDANCE_READ_SELF))]) -> dict[str, Any]:
        try:
            return {"items": service.own_attendance(context)}
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.get("/api/v1/me/report")
    def own_report(context: Annotated[AccessContext, Depends(require_permission(Permission.REPORTS_READ_SELF))]) -> dict[str, Any]:
        try:
            return service.own_report(context)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.post("/api/v1/me/password")
    def change_password(body: OwnPasswordChange, context: Annotated[AccessContext, Depends(require_authenticated_user)], request: Request) -> dict[str, bool]:
        require_write_session(request)
        try:
            service.change_own_password(context, body.current_password, body.new_password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"changed": True, "reauthentication_required": True}

    @router.get("/api/v1/admin/users")
    def users(_: Annotated[AccessContext, Depends(require_permission(Permission.USERS_MANAGE))]) -> dict[str, Any]:
        return {"items": service.list_users()}

    @router.get("/api/v1/admin/options")
    def options(_: Annotated[AccessContext, Depends(require_permission(Permission.USERS_MANAGE))]) -> dict[str, Any]:
        return service.options()

    @router.get("/api/v1/admin/audit")
    def security_audit(_: Annotated[AccessContext, Depends(require_permission(Permission.USERS_MANAGE))], limit: int = 500) -> dict[str, Any]:
        return {"items": service.security_audit(limit)}

    @router.get("/api/v1/admin/diagnostics")
    def diagnostics(request: Request, _: Annotated[AccessContext, Depends(require_permission(Permission.DIAGNOSTICS_READ))]) -> dict[str, Any]:
        return {
            "status": "ok",
            "schema_version": request.app.state.database_manager.validate_existing(),
            "release_id": request.app.state.settings.release_id,
        }

    @router.post("/api/v1/admin/users", status_code=201)
    def create_user(body: UserCreate, context: Annotated[AccessContext, Depends(_write_permission(Permission.USERS_MANAGE))]) -> dict[str, Any]:
        try:
            return service.create_user(body, context)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/v1/admin/users/{user_id}/roles")
    def roles(user_id: int, body: RoleUpdate, context: Annotated[AccessContext, Depends(_write_permission(Permission.USERS_MANAGE))]) -> dict[str, bool]:
        try:
            service.set_roles(user_id, body.roles, context)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"updated": True}

    @router.put("/api/v1/admin/users/{user_id}/permissions")
    def permissions(
        user_id: int,
        body: PermissionGrantUpdate,
        context: Annotated[
            AccessContext, Depends(_write_permission(Permission.USERS_MANAGE))
        ],
    ) -> dict[str, bool]:
        try:
            service.set_permission_grants(user_id, body.permissions, context)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"updated": True}

    @router.post("/api/v1/admin/users/{user_id}/deactivate")
    def deactivate(user_id: int, context: Annotated[AccessContext, Depends(_write_permission(Permission.USERS_MANAGE))]) -> dict[str, bool]:
        try:
            service.deactivate(user_id, context)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"deactivated": True}

    @router.post("/api/v1/admin/users/{user_id}/sessions/revoke")
    def revoke(user_id: int, context: Annotated[AccessContext, Depends(_write_permission(Permission.SESSIONS_REVOKE))]) -> dict[str, bool]:
        service.revoke(user_id, context)
        return {"revoked": True}

    @router.post("/api/v1/admin/users/{user_id}/password/reset")
    def reset_password(user_id: int, body: TemporaryPasswordReset, context: Annotated[AccessContext, Depends(_write_permission(Permission.USERS_MANAGE))]) -> dict[str, bool]:
        service.reset_password(user_id, body.temporary_password, context)
        return {"reset": True, "must_change_password": True}

    return router
