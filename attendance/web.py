from __future__ import annotations

import io
import secrets
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .auth import AuthManager, AuthSession, LoginLimitStatus
from .config import AppSettings
from .database import AttendanceRepository
from .models import CONFIRMATION_LABELS
from .services import build_coach_message, history_to_dataframe, summarize_records

ROOT_DIR = Path(__file__).resolve().parent.parent


class SyncOperation(BaseModel):
    operation_id: str = Field(min_length=8, max_length=100)
    member_id: int = Field(gt=0)
    base_version: int = Field(ge=1)
    confirmation_status: str
    present: bool | None = None
    notes: str = Field(default="", max_length=1000)


class SyncBatch(BaseModel):
    operations: list[SyncOperation] = Field(min_length=1, max_length=100)
    offline: bool = False


class SessionNotes(BaseModel):
    notes: str = Field(default="", max_length=4000)


class MemberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    position: str = Field(min_length=1, max_length=40)


class MemberUpdate(BaseModel):
    position: str = Field(min_length=1, max_length=40)
    active: bool


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Data inválida.") from exc


def _csv_response(dataframe: pd.DataFrame, filename: str) -> StreamingResponse:
    content = "\ufeff" + dataframe.to_csv(index=False)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _format_duration(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    for value, singular, plural in (
        (hours, "hora", "horas"),
        (minutes, "minuto", "minutos"),
        (seconds, "segundo", "segundos"),
    ):
        if value:
            unit = singular if value == 1 else plural
            parts.append(f"{value} {unit}")
    if not parts:
        return "0 segundos"
    return " e ".join(parts)


def _login_limit_message(status: LoginLimitStatus) -> str:
    policy_duration = _format_duration(status.window_seconds)
    remaining_duration = _format_duration(status.retry_after_seconds)
    return (
        f"Limite de {status.limit} tentativas atingido. "
        "A política atual bloqueia novas tentativas por até "
        f"{policy_duration}. Tente novamente em {remaining_duration}."
    )


def create_app(settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings.load(ROOT_DIR)
    repository = AttendanceRepository(settings.db_path)
    repository.validate_existing()
    auth = AuthManager(settings)
    templates = Jinja2Templates(directory=ROOT_DIR / "templates")

    application = FastAPI(
        title="Registro Oficial de Presenças",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = settings
    application.state.repository = repository
    application.state.auth = auth
    application.mount(
        "/static",
        StaticFiles(directory=ROOT_DIR / "static"),
        name="static",
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        maintenance_active = bool(
            settings.maintenance_file and settings.maintenance_file.is_file()
        )
        if maintenance_active and request.url.path not in {"/health", "/ready"}:
            response = JSONResponse(
                status_code=503,
                content={
                    "status": "maintenance",
                    "detail": "Atualização controlada em andamento.",
                },
                headers={"Retry-After": "30", "Cache-Control": "no-store"},
            )
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
            "form-action 'self'; manifest-src 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def session_from_request(request: Request) -> AuthSession | None:
        return auth.read_token(request.cookies.get(auth.cookie_name))

    def require_session(request: Request) -> AuthSession:
        session = session_from_request(request)
        if session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return session

    def require_write_session(request: Request) -> AuthSession:
        session = require_session(request)
        supplied = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(supplied, session.csrf_token):
            raise HTTPException(status_code=403, detail="Token CSRF inválido.")
        return session

    def session_payload(training_date: date) -> dict[str, Any]:
        training = repository.get_or_create_session(training_date)
        session_id = int(training["id"])
        records = repository.get_session_records(session_id)
        summary = summarize_records(records)
        return {
            "session": training,
            "records": records,
            "summary": {
                "confirmed": len(summary["confirmed"]),
                "pending": len(summary["pending"]),
                "cancelled": len(summary["cancelled"]),
                "present": len(summary["present"]),
                "absent": len(summary["absent"]),
                "unknown_presence": len(summary["unknown_presence"]),
            },
            "coach_message": build_coach_message(
                training_date,
                records,
                is_finalized=bool(training["is_finalized"]),
            ),
            "confirmation_labels": CONFIRMATION_LABELS,
        }

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready")
    def readiness() -> dict[str, str | int]:
        schema_version = repository.validate_existing()
        return {
            "status": "ok",
            "database": "ready",
            "schema_version": schema_version,
            "release_id": settings.release_id,
        }

    @application.get("/robots.txt", response_class=PlainTextResponse)
    def robots() -> str:
        return "User-agent: *\nDisallow: /\n"

    @application.get("/sw.js")
    def service_worker() -> FileResponse:
        return FileResponse(
            ROOT_DIR / "static" / "sw.js",
            media_type="application/javascript",
            headers={
                "Service-Worker-Allowed": "/",
                "Cache-Control": "no-cache",
            },
        )

    @application.get("/", response_class=HTMLResponse)
    def root(request: Request) -> RedirectResponse:
        target = "/app" if session_from_request(request) else "/login"
        return RedirectResponse(target, status_code=303)

    @application.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> Response:
        if session_from_request(request):
            return RedirectResponse("/app", status_code=303)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": None, "username": settings.admin_username},
        )

    @application.post("/login", response_class=HTMLResponse)
    def login(
        request: Request,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
    ) -> Response:
        client_key = request.client.host if request.client else "unknown"
        limit_status = auth.limiter.status(client_key)
        if limit_status.blocked:
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": _login_limit_message(limit_status),
                    "username": username,
                },
                status_code=429,
                headers={
                    "Retry-After": str(limit_status.retry_after_seconds),
                },
            )
        if not auth.verify_credentials(username, password):
            limit_status = auth.limiter.fail(client_key)
            if limit_status.blocked:
                return templates.TemplateResponse(
                    request,
                    "login.html",
                    {
                        "error": _login_limit_message(limit_status),
                        "username": username,
                    },
                    status_code=429,
                    headers={
                        "Retry-After": str(limit_status.retry_after_seconds),
                    },
                )
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Usuário ou senha inválidos.", "username": username},
                status_code=401,
            )
        auth.limiter.clear(client_key)
        token, _ = auth.create_token()
        response = RedirectResponse("/app", status_code=303)
        response.set_cookie(
            auth.cookie_name,
            token,
            max_age=settings.session_max_age_seconds,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        return response

    @application.post("/logout")
    def logout() -> RedirectResponse:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(auth.cookie_name, path="/")
        return response

    @application.get("/app", response_class=HTMLResponse)
    def app_shell(request: Request) -> Response:
        if session_from_request(request) is None:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request, "app.html", {})

    @application.get("/api/v1/auth/session")
    def auth_session(
        session: AuthSession = Depends(require_session),
    ) -> dict[str, str]:
        return {"username": session.username, "csrf_token": session.csrf_token}

    @application.get("/api/v1/session")
    def get_session(
        training_date: str,
        _: AuthSession = Depends(require_session),
    ) -> dict[str, Any]:
        return session_payload(_parse_date(training_date))

    @application.put("/api/v1/sessions/{session_id}/records")
    def sync_session_records(
        session_id: int,
        batch: SyncBatch,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        source = "pwa-offline" if batch.offline else "pwa-online"
        try:
            results = repository.sync_records(
                session_id,
                [item.model_dump() for item in batch.operations],
                source=source,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"results": results}

    @application.post("/api/v1/sessions/{session_id}/finalize")
    def finalize_session(
        session_id: int,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        changed = repository.finalize_session(session_id, source="pwa-finalize")
        session = repository.get_session(session_id)
        return {"changed": changed, "session": session}

    @application.post("/api/v1/sessions/{session_id}/reopen")
    def reopen_session(
        session_id: int,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        repository.reopen_session(session_id)
        return {"session": repository.get_session(session_id)}

    @application.put("/api/v1/sessions/{session_id}/notes")
    def update_session_notes(
        session_id: int,
        body: SessionNotes,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        repository.update_session_notes(session_id, body.notes)
        return {"session": repository.get_session(session_id)}

    @application.get("/api/v1/history")
    def history(_: AuthSession = Depends(require_session)) -> dict[str, Any]:
        return {"items": repository.get_history()}

    @application.get("/api/v1/audit")
    def audit(
        limit: int = 500,
        _: AuthSession = Depends(require_session),
    ) -> dict[str, Any]:
        return {"items": repository.get_audit_log(limit=min(max(limit, 1), 1000))}

    @application.get("/api/v1/members")
    def members(_: AuthSession = Depends(require_session)) -> dict[str, Any]:
        return {"items": repository.list_members(include_inactive=True)}

    @application.post("/api/v1/members")
    def add_member(
        body: MemberCreate,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        try:
            repository.add_member(body.name, body.position)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"items": repository.list_members(include_inactive=True)}

    @application.put("/api/v1/members/{member_id}")
    def update_member(
        member_id: int,
        body: MemberUpdate,
        _: AuthSession = Depends(require_write_session),
    ) -> dict[str, Any]:
        try:
            repository.update_member(
                member_id,
                position=body.position,
                active=body.active,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"items": repository.list_members(include_inactive=True)}

    @application.get("/api/v1/exports/session/{session_id}.csv")
    def export_session(
        session_id: int,
        _: AuthSession = Depends(require_session),
    ) -> StreamingResponse:
        session = repository.get_session(session_id)
        records = repository.get_session_records(session_id)
        rows = [
            {
                "training_date": session["training_date"],
                "is_finalized": session["is_finalized"],
                **record,
            }
            for record in records
        ]
        return _csv_response(
            history_to_dataframe(rows),
            f"presencas_{session['training_date']}.csv",
        )

    @application.get("/api/v1/exports/history.csv")
    def export_history(
        _: AuthSession = Depends(require_session),
    ) -> StreamingResponse:
        return _csv_response(
            history_to_dataframe(repository.get_history()),
            "historico_completo_presencas.csv",
        )

    @application.get("/api/v1/backup")
    def download_backup(
        _: AuthSession = Depends(require_session),
    ) -> FileResponse:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = repository.backup_to(
            (settings.backup_dir or ROOT_DIR / "backups")
            / f"presencas-{timestamp}.db"
        )
        return FileResponse(
            backup_path,
            filename=backup_path.name,
            media_type="application/vnd.sqlite3",
        )

    return application
