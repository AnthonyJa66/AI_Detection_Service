import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import health
from app.api.router import api_router
from app.core.config import get_service_settings
from app.websocket.router import router as websocket_router


logger = logging.getLogger("ai_detection_service.main")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    settings = get_service_settings()
    logger.info("Creating AI Detection Service FastAPI application.")
    application = FastAPI(
        title=settings.name,
        version=settings.version,
        openapi_url="/openapi.json",
    )

    application.include_router(api_router)
    application.include_router(health.router, prefix=settings.api_prefix)
    application.include_router(websocket_router)

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        logger.warning("Request validation failed: %s", exc)
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
        logger.exception("Unhandled API exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"message": "Internal server error."},
        )

    return application


app = create_app()
