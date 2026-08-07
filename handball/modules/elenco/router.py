from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from handball.core.auth import (
    AuthSession,
    require_write_session,
    session_from_request,
)
from handball.core.authorization import (
    AccessContext,
    Permission,
    require_permission,
)
from handball.modules.usuarios.service import IdentityService

from .schemas import (
    MemberCreate,
    MemberUpdate,
    RankingAnswer,
    RankingSessionCreate,
    RefinementUpdate,
)
from .service import RosterService


def _require_manage(context: AuthSession) -> None:
    if Permission.MEMBERS_MANAGE not in context.permissions:
        raise HTTPException(status_code=403)


def create_router(
    service: RosterService,
    identity_service: IdentityService,
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/app/elenco", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_from_request(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if Permission.MEMBERS_READ_TEAM not in session.permissions:
            raise HTTPException(status_code=403)
        team_view = identity_service.resolve_active_team_view(session.to_access_context())
        return templates.TemplateResponse(
            request,
            "elenco/index.html",
            {
                "username": session.username,
                "session": session,
                "organization": team_view["organization"],
                "team_theme": team_view["team_theme"],
            },
        )

    @router.get("/api/v1/elenco/members")
    def members(
        _: AccessContext = Depends(require_permission(Permission.MEMBERS_READ_TEAM)),
    ) -> dict[str, Any]:
        return {"items": service.members()}

    @router.post("/api/v1/elenco/members")
    def add_member(
        body: MemberCreate,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        _require_manage(context)
        try:
            return {"items": service.add_member(
                body.name, body.position, attack_positions=body.attack_positions,
                defensive_positions=body.defensive_positions, actor_user_id=context.user_id or None,
            )}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/v1/elenco/members/{member_id}")
    def update_member(
        member_id: int,
        body: MemberUpdate,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        _require_manage(context)
        try:
            return {"items": service.update_member(
                member_id,
                position=body.position,
                active=body.active,
                attack_positions=body.attack_positions,
                defensive_positions=body.defensive_positions,
                actor_user_id=context.user_id or None,
            )}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/v1/elenco/layers")
    def layers(
        _: AccessContext = Depends(require_permission(Permission.MEMBERS_READ_TEAM)),
    ) -> dict[str, Any]:
        return service.overview()

    @router.post("/api/v1/elenco/ranking/sessions")
    def start_ranking(
        body: RankingSessionCreate,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        _require_manage(context)
        try:
            return service.start_ranking(
                scope=body.scope,
                member_id=body.member_id,
                rerank=body.rerank,
                actor_user_id=context.user_id or 0,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/api/v1/elenco/ranking/sessions/{session_id}/answers")
    def answer_ranking(
        session_id: str,
        body: RankingAnswer,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        _require_manage(context)
        try:
            return service.answer(
                session_id,
                reference_member_id=body.reference_member_id,
                outcome=body.outcome,
                actor_user_id=context.user_id or 0,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.delete("/api/v1/elenco/ranking/sessions/{session_id}")
    def cancel_ranking(
        session_id: str,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        _require_manage(context)
        try:
            return service.cancel(session_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.put("/api/v1/elenco/layers/{layer_id}/refinements")
    def save_refinement(
        layer_id: int,
        body: RefinementUpdate,
        context: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        _require_manage(context)
        try:
            return service.save_refinement(
                layer_id,
                position=body.position,
                member_ids=body.member_ids,
                actor_user_id=context.user_id or 0,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/v1/elenco/metrics")
    def metrics(
        semester: str | None = None,
        _: AccessContext = Depends(require_permission(Permission.MEMBERS_READ_TEAM)),
    ) -> dict[str, Any]:
        try:
            return service.metrics(semester)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
