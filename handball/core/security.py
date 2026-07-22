from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .config import AppSettings


CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
    "form-action 'self'; manifest-src 'self'"
)


def install_security_middleware(application: FastAPI, settings: AppSettings) -> None:
    @application.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
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
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
