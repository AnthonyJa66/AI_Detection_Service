"""Common JSON response schemas."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Health-check response payload."""

    service: str
    version: str
    status: str


class MessageResponse(BaseModel):
    """Generic message response payload."""

    message: str

