"""Service health API routes."""

from fastapi import APIRouter

from app.core.config import get_service_settings
from app.schemas.common import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return API service health metadata as JSON."""

    settings = get_service_settings()
    return HealthResponse(
        service=settings.name,
        version=settings.version,
        status="ok",
    )

