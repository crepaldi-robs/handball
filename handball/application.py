from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from handball.core.auth import AuthManager, create_auth_router, session_from_request
from handball.core.config import AppSettings
from handball.core.security import install_security_middleware
from handball.database import DatabaseManager, UnitOfWorkFactory
from handball.modules.calendario.router import create_router as create_calendar_router
from handball.modules.calendario.service import CalendarService
from handball.modules.consultas.router import create_router as create_sql_explorer_router
from handball.modules.consultas.service import SqlExplorerService
from handball.modules.estatisticas.router import (
    create_router as create_statistics_router,
)
from handball.modules.estatisticas.service import StatisticsService
from handball.modules.hub.router import create_router as create_hub_router
from handball.modules.presencas.router import create_router as create_attendance_router
from handball.modules.presencas.service import AttendanceService
from handball.modules.usuarios.router import create_router as create_users_router
from handball.modules.usuarios.service import IdentityService


ROOT_DIR = Path(__file__).resolve().parent.parent


def create_app(
    settings: AppSettings | None = None,
    database_manager: DatabaseManager | None = None,
    auth_manager: AuthManager | None = None,
) -> FastAPI:
    """Compõe um único processo FastAPI para todos os módulos."""

    settings = settings or AppSettings.load(ROOT_DIR)
    database_manager = database_manager or DatabaseManager.from_environment(
        ROOT_DIR,
        config_path=settings.config_path,
    )
    database_manager.validate_existing()
    unit_of_work_factory = UnitOfWorkFactory(database_manager)
    auth_manager = auth_manager or AuthManager(settings, unit_of_work_factory)
    templates = Jinja2Templates(directory=ROOT_DIR / "templates")

    attendance_service = AttendanceService(
        unit_of_work_factory,
        database_manager,
    )
    statistics_service = StatisticsService()
    calendar_service = CalendarService(unit_of_work_factory)
    sql_explorer_service = SqlExplorerService(unit_of_work_factory, database_manager)
    identity_service = IdentityService(unit_of_work_factory)

    application = FastAPI(
        title="Hub Handebol",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = settings
    application.state.database_manager = database_manager
    application.state.auth = auth_manager
    application.state.attendance_service = attendance_service
    application.mount(
        "/static",
        StaticFiles(directory=ROOT_DIR / "static"),
        name="static",
    )
    install_security_middleware(application, settings)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready")
    def readiness() -> dict[str, str | int]:
        schema_version = database_manager.validate_existing()
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

    application.include_router(create_auth_router(settings, templates))
    application.include_router(create_hub_router(templates))
    application.include_router(create_attendance_router(attendance_service, templates))
    application.include_router(create_statistics_router(statistics_service, templates))
    application.include_router(create_calendar_router(calendar_service, templates))
    application.include_router(create_sql_explorer_router(sql_explorer_service, templates))
    application.include_router(create_users_router(identity_service, templates))
    return application
