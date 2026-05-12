"""FastAPI service configuration.

This module is intentionally small for the first migration step. The existing
Flask runtime and detection pipeline remain untouched while the REST/WebSocket
service skeleton is introduced beside them.
"""

from functools import lru_cache

from pydantic import BaseModel, Field


class ServiceSettings(BaseModel):
    """Runtime metadata for the API service."""

    name: str = "AI Detection Service"
    version: str = "0.1.0"
    api_prefix: str = Field(default="/api/v1", pattern=r"^/")


@lru_cache
def get_service_settings() -> ServiceSettings:
    """Return cached service settings for FastAPI initialization."""

    return ServiceSettings()

