"""RTSP camera service.

This module only manages RTSP capture lifecycle and latest-frame cache. It does
not perform inference, WebSocket pushing, REST routing, or database access.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

import cv2
import numpy as np
from pydantic import BaseModel, Field, field_validator


logger = logging.getLogger("ai_detection_service.camera_service")


class CameraStreamStatus(str, Enum):
    """Runtime status for an RTSP camera worker."""

    STOPPED = "stopped"
    CONNECTING = "connecting"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class CameraConfig(BaseModel):
    """RTSP camera configuration used by CameraService."""

    camera_id: str = Field(..., min_length=1)
    rtsp_url: str = Field(..., min_length=1)
    enabled: bool = True
    reconnect_interval_seconds: float = Field(default=5.0, ge=0.1)
    read_retry_limit: int = Field(default=3, ge=1)
    open_timeout_milliseconds: int = Field(default=5000, ge=1000)
    read_timeout_milliseconds: int = Field(default=5000, ge=1000)

    @field_validator("camera_id", "rtsp_url")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped_value = value.strip()
        if not stripped_value:
            raise ValueError("value must not be empty")
        return stripped_value


class CameraRuntimeState(BaseModel):
    """Thread-safe snapshot of one camera worker status."""

    camera_id: str
    status: CameraStreamStatus
    running: bool
    has_frame: bool
    last_error: str = ""
    last_frame_at: float | None = None
    reconnect_count: int = 0


class _CameraWorker:
    """Background RTSP reader for a single camera."""

    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(
            f"ai_detection_service.camera_service.{config.camera_id}"
        )
        self._frame_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: cv2.VideoCapture | None = None
        self._latest_frame: np.ndarray | None = None
        self._status = CameraStreamStatus.STOPPED
        self._last_error = ""
        self._last_frame_at: float | None = None
        self._reconnect_count = 0

    def start(self) -> None:
        """Start the camera reader thread."""

        with self._state_lock:
            if self._thread and self._thread.is_alive():
                self.logger.warning("Camera worker is already running.")
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name=f"CameraService-{self.config.camera_id}",
                daemon=True,
            )
            self._set_status(CameraStreamStatus.CONNECTING, "")
            self._thread.start()
            self.logger.info("Camera worker started.")

    def stop(self, join_timeout_seconds: float = 5.0) -> None:
        """Stop the camera reader thread and release capture resources."""

        self.logger.info("Stopping camera worker.")
        self._stop_event.set()
        self._release_capture()

        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=join_timeout_seconds)
            if thread.is_alive():
                self.logger.warning("Camera worker did not stop within timeout.")

        self._release_capture()
        with self._frame_lock:
            self._latest_frame = None
        self._set_status(CameraStreamStatus.STOPPED, "")
        self.logger.info("Camera worker stopped.")

    def get_latest_frame(self, copy: bool = True) -> np.ndarray | None:
        """Return the latest cached frame."""

        with self._frame_lock:
            if self._latest_frame is None:
                return None
            if copy:
                return self._latest_frame.copy()
            return self._latest_frame

    def get_state(self) -> CameraRuntimeState:
        """Return a Pydantic status snapshot."""

        with self._state_lock:
            thread_alive = bool(self._thread and self._thread.is_alive())
            status = self._status
            last_error = self._last_error
            last_frame_at = self._last_frame_at
            reconnect_count = self._reconnect_count

        with self._frame_lock:
            has_frame = self._latest_frame is not None

        return CameraRuntimeState(
            camera_id=self.config.camera_id,
            status=status,
            running=thread_alive,
            has_frame=has_frame,
            last_error=last_error,
            last_frame_at=last_frame_at,
            reconnect_count=reconnect_count,
        )

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                capture = self._open_capture()
                if capture is None:
                    self._wait_before_reconnect("failed to open RTSP stream")
                    continue

                self._capture = capture
                self._set_status(CameraStreamStatus.RUNNING, "")
                self.logger.info("Camera stream connected.")
                read_failures = 0

                while not self._stop_event.is_set():
                    success, frame = capture.read()
                    if not success or frame is None or frame.size == 0:
                        read_failures += 1
                        self.logger.warning(
                            "Failed to read frame. camera_id=%s failures=%s",
                            self.config.camera_id,
                            read_failures,
                        )
                        if read_failures >= self.config.read_retry_limit:
                            break
                        time.sleep(0.05)
                        continue

                    read_failures = 0
                    with self._frame_lock:
                        self._latest_frame = frame
                    with self._state_lock:
                        self._last_frame_at = time.time()

                self._release_capture()
                if not self._stop_event.is_set():
                    self._wait_before_reconnect("frame read failed")
            except Exception as exc:
                self.logger.exception("Camera worker error: %s", exc)
                self._release_capture()
                if not self._stop_event.is_set():
                    self._wait_before_reconnect(str(exc))

        self._release_capture()
        self._set_status(CameraStreamStatus.STOPPED, "")

    def _open_capture(self) -> cv2.VideoCapture | None:
        self._set_status(CameraStreamStatus.CONNECTING, "")
        self.logger.info(
            "Opening RTSP stream. camera_id=%s url=%s",
            self.config.camera_id,
            _mask_rtsp_url(self.config.rtsp_url),
        )

        capture = cv2.VideoCapture(self.config.rtsp_url, cv2.CAP_FFMPEG)
        self._set_capture_property(
            capture,
            "CAP_PROP_OPEN_TIMEOUT_MSEC",
            float(self.config.open_timeout_milliseconds),
        )
        self._set_capture_property(
            capture,
            "CAP_PROP_READ_TIMEOUT_MSEC",
            float(self.config.read_timeout_milliseconds),
        )
        self._set_capture_property(capture, "CAP_PROP_BUFFERSIZE", 1.0)

        if not capture.isOpened():
            capture.release()
            self._set_status(CameraStreamStatus.ERROR, "Unable to open RTSP stream.")
            self.logger.error(
                "Unable to open RTSP stream. camera_id=%s",
                self.config.camera_id,
            )
            return None

        return capture

    def _wait_before_reconnect(self, reason: str) -> None:
        with self._state_lock:
            self._reconnect_count += 1
            reconnect_count = self._reconnect_count

        self._set_status(CameraStreamStatus.RECONNECTING, reason)
        self.logger.warning(
            "Reconnecting camera stream. camera_id=%s reconnect_count=%s reason=%s",
            self.config.camera_id,
            reconnect_count,
            reason,
        )
        self._stop_event.wait(self.config.reconnect_interval_seconds)

    def _set_status(self, status: CameraStreamStatus, error_message: str) -> None:
        with self._state_lock:
            self._status = status
            self._last_error = error_message

    def _release_capture(self) -> None:
        capture = self._capture
        self._capture = None
        if capture is None:
            return
        try:
            capture.release()
        except Exception as exc:
            self.logger.exception("Failed to release RTSP capture: %s", exc)

    def _set_capture_property(
        self,
        capture: cv2.VideoCapture,
        property_name: str,
        value: float,
    ) -> None:
        property_id = getattr(cv2, property_name, None)
        if property_id is None:
            return
        try:
            capture.set(property_id, value)
        except Exception as exc:
            self.logger.debug(
                "Capture property not supported. property=%s error=%s",
                property_name,
                exc,
            )


class CameraService:
    """Manage multiple RTSP camera workers."""

    def __init__(self, cameras: Iterable[CameraConfig] | None = None) -> None:
        self.logger = logger
        self._lock = threading.RLock()
        self._workers: dict[str, _CameraWorker] = {}

        for camera in cameras or []:
            self.add_camera(camera)

    def add_camera(self, config: CameraConfig) -> None:
        """Register one camera without starting inference or API logic."""

        with self._lock:
            if config.camera_id in self._workers:
                raise ValueError(f"Camera already exists: {config.camera_id}")
            self._workers[config.camera_id] = _CameraWorker(config)

        self.logger.info("Camera registered. camera_id=%s", config.camera_id)

    def remove_camera(self, camera_id: str) -> bool:
        """Stop and remove one camera."""

        with self._lock:
            worker = self._workers.pop(camera_id, None)

        if worker is None:
            self.logger.warning("Camera not found for removal. camera_id=%s", camera_id)
            return False

        worker.stop()
        self.logger.info("Camera removed. camera_id=%s", camera_id)
        return True

    def start(self) -> None:
        """Start all enabled camera workers."""

        with self._lock:
            workers = list(self._workers.values())

        for worker in workers:
            if not worker.config.enabled:
                self.logger.info(
                    "Skipping disabled camera. camera_id=%s",
                    worker.config.camera_id,
                )
                continue
            worker.start()

    def stop(self) -> None:
        """Stop all camera workers."""

        with self._lock:
            workers = list(self._workers.values())

        for worker in workers:
            worker.stop()

    def start_camera(self, camera_id: str) -> bool:
        """Start one registered camera."""

        worker = self._get_worker(camera_id)
        if worker is None:
            self.logger.warning("Camera not found for start. camera_id=%s", camera_id)
            return False
        worker.start()
        return True

    def stop_camera(self, camera_id: str) -> bool:
        """Stop one registered camera."""

        worker = self._get_worker(camera_id)
        if worker is None:
            self.logger.warning("Camera not found for stop. camera_id=%s", camera_id)
            return False
        worker.stop()
        return True

    def get_latest_frame(
        self,
        camera_id: str,
        copy: bool = True,
    ) -> np.ndarray | None:
        """Return the latest cached frame for one camera."""

        worker = self._get_worker(camera_id)
        if worker is None:
            self.logger.warning(
                "Camera not found when requesting latest frame. camera_id=%s",
                camera_id,
            )
            return None
        return worker.get_latest_frame(copy=copy)

    def get_camera_state(self, camera_id: str) -> CameraRuntimeState | None:
        """Return one camera runtime state."""

        worker = self._get_worker(camera_id)
        if worker is None:
            self.logger.warning(
                "Camera not found when requesting state. camera_id=%s",
                camera_id,
            )
            return None
        return worker.get_state()

    def get_all_camera_states(self) -> dict[str, CameraRuntimeState]:
        """Return runtime states for all registered cameras."""

        with self._lock:
            workers = dict(self._workers)

        return {
            camera_id: worker.get_state()
            for camera_id, worker in workers.items()
        }

    def _get_worker(self, camera_id: str) -> _CameraWorker | None:
        with self._lock:
            return self._workers.get(camera_id)


def _mask_rtsp_url(rtsp_url: str) -> str:
    try:
        parts = urlsplit(rtsp_url)
        if not parts.username:
            return rtsp_url

        hostname = parts.hostname or ""
        port_suffix = f":{parts.port}" if parts.port else ""
        netloc = f"***:***@{hostname}{port_suffix}"
        return urlunsplit(
            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
        )
    except Exception:
        return "<invalid-rtsp-url>"
