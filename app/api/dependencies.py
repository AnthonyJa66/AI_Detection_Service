"""FastAPI dependencies for REST API routes."""

from __future__ import annotations

import logging

from app.core.config import ServiceSettings, get_service_settings
from app.services.camera_service import CameraService


logger = logging.getLogger("ai_detection_service.api.dependencies")
_camera_service = CameraService()


def get_camera_service() -> CameraService:
    """Return the shared camera service instance."""

    logger.debug("Providing CameraService dependency.")
    return _camera_service


def get_settings() -> ServiceSettings:
    """Return service settings for API routes."""

    logger.debug("Providing ServiceSettings dependency.")
    return get_service_settings()
