"""FastAPI entrypoint for the AI Detection Service.

The legacy Flask application is intentionally left in place. This module starts
the new REST API + WebSocket service skeleton for gradual migration.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_service_settings
from app.websocket.router import router as websocket_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    settings = get_service_settings()
    application = FastAPI(
        title=settings.name,
        version=settings.version,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    application.include_router(api_router, prefix=settings.api_prefix)
    application.include_router(websocket_router)

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "message": "Request validation failed.",
                "errors": exc.errors(),
            },
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"message": "Internal server error."},
        )

    return application


app = create_app()
