"""Pydantic schemas for YOLO detection output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DetectionResult(BaseModel):
    """Single object detection result."""

    class_id: int
    class_name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: list[int] = Field(..., min_length=4, max_length=4)
