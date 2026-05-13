"""Camera REST API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import get_camera_service
from app.services.camera_service import CameraService, CameraStreamStatus


logger = logging.getLogger("ai_detection_service.api.cameras")
router = APIRouter(prefix="/api/cameras", tags=["cameras"])


class CameraStatusResponse(BaseModel):
    """Camera runtime status response."""

    camera_id: str
    status: CameraStreamStatus
    running: bool
    has_frame: bool
    last_error: str = ""
    last_frame_at: float | None = None
    reconnect_count: int = 0


class CameraStatusListResponse(BaseModel):
    """All camera statuses response."""

    cameras: list[CameraStatusResponse]


class LatestFrameResponse(BaseModel):
    """Latest camera frame metadata response."""

    camera_id: str
    available: bool
    width: int | None = None
    height: int | None = None
    channels: int | None = None


@router.get("/status", response_model=CameraStatusListResponse)
async def get_camera_status(
    camera_service: CameraService = Depends(get_camera_service),
) -> CameraStatusListResponse:
    """Return all RTSP camera runtime statuses."""

    logger.info("Camera status requested.")
    states = camera_service.get_all_camera_states()
    return CameraStatusListResponse(
        cameras=[
            CameraStatusResponse(**state.model_dump())
            for state in states.values()
        ]
    )


@router.get("/{camera_id}/latest", response_model=LatestFrameResponse)
async def get_latest_camera_frame(
    camera_id: str,
    camera_service: CameraService = Depends(get_camera_service),
) -> LatestFrameResponse:
    """Return metadata for the latest cached frame of one camera."""

    logger.info("Latest frame requested. camera_id=%s", camera_id)
    if camera_service.get_camera_state(camera_id) is None:
        logger.warning("Camera not found. camera_id=%s", camera_id)
        raise HTTPException(status_code=404, detail="Camera not found.")

    frame = camera_service.get_latest_frame(camera_id)
    if frame is None:
        return LatestFrameResponse(camera_id=camera_id, available=False)

    height = int(frame.shape[0])
    width = int(frame.shape[1])
    channels = int(frame.shape[2]) if len(frame.shape) > 2 else 1
    return LatestFrameResponse(
        camera_id=camera_id,
        available=True,
        width=width,
        height=height,
        channels=channels,
    )
