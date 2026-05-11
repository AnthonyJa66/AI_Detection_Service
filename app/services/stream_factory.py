from __future__ import annotations

from app.services.camera_stream import (
    SOURCE_TYPE_NVR_RTSP,
    SOURCE_TYPE_RTSP_CAMERA,
    CameraConfig,
    CameraStream,
)


class StreamFactory:
    def create(self, camera_config: CameraConfig) -> CameraStream:
        if camera_config.source_type in {
            SOURCE_TYPE_RTSP_CAMERA,
            SOURCE_TYPE_NVR_RTSP,
        }:
            return CameraStream(camera_config)

        raise ValueError(f"Unsupported source type: {camera_config.source_type}")
