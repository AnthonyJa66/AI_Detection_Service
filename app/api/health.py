"""Service health API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.api.dependencies import get_settings
from app.core.config import ServiceSettings
from app.schemas.common import HealthResponse


logger = logging.getLogger("ai_detection_service.api.health")
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(
    settings: ServiceSettings = Depends(get_settings),
) -> HealthResponse:
    """Return API service health metadata as JSON."""

    logger.info("Health check requested.")
    return HealthResponse(
        service=settings.name,
        version=settings.version,
        status="ok",
    )
