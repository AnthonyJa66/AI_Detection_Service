"""单路摄像头拉流线程。

这里负责通过 OpenCV/FFmpeg 读取 RTSP 或 NVR RTSP，并维护最新帧与运行状态。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import cv2

from app.logger import get_logger
from app.models.video_source import (
    SOURCE_TYPE_NVR_RTSP,
    SOURCE_TYPE_RTSP_CAMERA,
    SUPPORTED_SOURCE_TYPES,
)


STREAM_STATUS_STOPPED = "stopped"
STREAM_STATUS_CONNECTING = "connecting"
STREAM_STATUS_RUNNING = "running"
STREAM_STATUS_RECONNECTING = "reconnecting"
STREAM_STATUS_ERROR = "error"
FFMPEG_CAPTURE_OPTIONS = (
    "rtsp_transport;udp|buffer_size;1024000|max_delay;500000|stimeout;2000000"
)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = FFMPEG_CAPTURE_OPTIONS


@dataclass(slots=True)
class CameraConfig:
    """单路摄像头运行配置。

    rtsp_url 用于原始流配置，detection_rtsp_url 可单独指定更稳定的检测专用流。
    """

    id: str
    name: str
    source_type: str
    rtsp_url: str
    detection_rtsp_url: str
    enabled: bool
    fps_target: int
    retry_interval_seconds: int
    max_reconnect_attempts: int
    resolution_width: int
    resolution_height: int
    location: str = ""
    nvr_name: str = ""
    nvr_host: str = ""
    nvr_port: int = 554
    channel_no: str = ""
    username: str = ""
    password: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CameraConfig":
        resolution = data.get("resolution", {})
        known_keys = {
            "id",
            "camera_id",
            "name",
            "source_type",
            "rtsp_url",
            "detection_rtsp_url",
            "enabled",
            "fps_target",
            "retry_interval_seconds",
            "max_reconnect_attempts",
            "resolution",
            "location",
            "nvr_name",
            "nvr_host",
            "nvr_port",
            "channel_no",
            "username",
            "password",
        }
        extra = {key: value for key, value in data.items() if key not in known_keys}
        camera_id = str(data.get("camera_id") or data["id"])
        return cls(
            id=camera_id,
            name=str(data["name"]),
            source_type=str(data.get("source_type") or SOURCE_TYPE_RTSP_CAMERA),
            rtsp_url=str(data.get("rtsp_url", "")),
            detection_rtsp_url=str(data.get("detection_rtsp_url", "")),
            enabled=bool(data["enabled"]),
            fps_target=int(data["fps_target"]),
            retry_interval_seconds=int(data["retry_interval_seconds"]),
            max_reconnect_attempts=int(data["max_reconnect_attempts"]),
            resolution_width=int(resolution["width"]),
            resolution_height=int(resolution["height"]),
            location=str(data.get("location", "")),
            nvr_name=str(data.get("nvr_name", "")),
            nvr_host=str(data.get("nvr_host", "")),
            nvr_port=int(data.get("nvr_port", 554) or 554),
            channel_no=str(data.get("channel_no", "")),
            username=str(data.get("username", "")),
            password=str(data.get("password", "")),
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["camera_id"] = payload["id"]
        payload["resolution"] = {
            "width": payload.pop("resolution_width"),
            "height": payload.pop("resolution_height"),
        }
        return payload

    def resolve_stream_url(self) -> str:
        """返回检测线程实际使用的 RTSP 地址。"""
        return self.detection_rtsp_url.strip() or self.rtsp_url.strip()


class CameraStream:
    """封装单路拉流线程、重连逻辑和最新帧缓存。"""

    def __init__(self, config: CameraConfig):
        self.config = config
        self.logger = get_logger(f"video_monitor.camera.{self.config.id}")
        self._frame_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: cv2.VideoCapture | None = None
        self._latest_frame = None
        self._status = STREAM_STATUS_STOPPED
        self._last_error = ""
        self._reconnect_attempts = 0
        self._frames_read = 0
        self._last_fps = 0.0
        self._fps_window_started_at = time.monotonic()
        self._last_frame_at = None
        self._latest_frame_id = 0
        self.running = False
        self._read_failures = 0
        self._first_frame_logged = False

    def start(self) -> None:
        with self._status_lock:
            if self.running or (self._thread and self._thread.is_alive()):
                self.logger.warning("Camera stream is already running.")
                return

            self._stop_event.clear()
            self.running = True
            self._thread = threading.Thread(
                target=self._run_loop,
                name=f"CameraStream-{self.config.id}",
                daemon=True,
            )
            self._thread.start()
            self.logger.info("Camera stream thread started.")

    def stop(self, join_timeout: float = 5.0) -> None:
        self.logger.info("Stopping camera stream.")
        self._stop_event.set()
        self._release_capture()

        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                self.logger.warning("Camera stream thread did not exit within timeout.")

        self._release_capture()
        with self._frame_lock:
            self._latest_frame = None
        self.running = False
        self._set_status(STREAM_STATUS_STOPPED, "")
        self.logger.info("Camera stream stopped.")

    def update_config(self, config: CameraConfig) -> bool:
        previous_config = self.config
        requires_restart = self._requires_restart(previous_config, config)
        self.config = config
        self.logger.info(
            "Camera config updated. camera_id=%s requires_restart=%s",
            config.id,
            requires_restart,
        )
        return requires_restart

    def get_frame(self, copy: bool = True):
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            if copy:
                return self._latest_frame.copy()
            return self._latest_frame

    def get_frame_packet(self, copy: bool = True) -> dict[str, Any] | None:
        """返回带时间戳和 frame_id 的帧包。"""
        with self._frame_lock:
            if self._latest_frame is None:
                return None

            frame = self._latest_frame.copy() if copy else self._latest_frame
            return {
                "frame": frame,
                "frame_id": self._latest_frame_id,
                "captured_at": self._last_frame_at,
            }

    def get_status(self) -> dict[str, Any]:
        """返回主界面和 API 使用的运行状态快照。"""
        with self._status_lock:
            return {
                "camera_id": self.config.id,
                "camera_name": self.config.name,
                "enabled": self.config.enabled,
                "source_type": self.config.source_type,
                # 用于区分当前检测线程读的是主码流还是检测专用流。
                "stream_url_role": (
                    "detection_rtsp_url"
                    if self.config.detection_rtsp_url.strip()
                    else "rtsp_url"
                ),
                "status": self._status,
                "fps": round(self._last_fps, 2),
                "last_error": self._last_error,
                "reconnect_attempts": self._reconnect_attempts,
                "last_frame_at": self._last_frame_at,
                "thread_alive": bool(self._thread and self._thread.is_alive()),
            }

    def _run_loop(self) -> None:
        """后台线程主循环：连接、读帧、失败重连。"""
        while not self._stop_event.is_set():
            try:
                if not self._connect():
                    if not self._handle_reconnect_wait("initial connection failed"):
                        break
                    continue

                self._reconnect_attempts = 0
                self._read_failures = 0
                self._set_status(STREAM_STATUS_RUNNING, "")
                self.logger.info("Camera stream is running.")

                while not self._stop_event.is_set():
                    if not self._read_frame():
                        break

                if self._stop_event.is_set():
                    break

                self._release_capture()
                if not self._handle_reconnect_wait("frame read failed"):
                    break
            except Exception as exc:
                self.logger.exception("Unexpected camera stream error: %s", exc)
                self._set_status(STREAM_STATUS_ERROR, str(exc))
                self._release_capture()
                if not self._handle_reconnect_wait(str(exc)):
                    break

        self._release_capture()
        self.running = False
        if self._stop_event.is_set():
            self._set_status(STREAM_STATUS_STOPPED, "")

    def _connect(self) -> bool:
        """建立底层 VideoCapture 连接。"""
        stream_url = self.config.resolve_stream_url()
        self._set_status(STREAM_STATUS_CONNECTING, "")
        self.logger.info(
            "Connecting to stream. camera_id=%s source_type=%s url=%s",
            self.config.id,
            self.config.source_type,
            mask_rtsp_url(stream_url),
        )
        self.logger.info(
            "detection worker using url: %s",
            mask_rtsp_url(stream_url),
        )

        if not stream_url:
            self._set_status(STREAM_STATUS_ERROR, "Stream URL is empty.")
            self.logger.error(
                "Stream URL is empty. camera_id=%s source_type=%s",
                self.config.id,
                self.config.source_type,
            )
            return False

        self._release_capture()
        capture = self._open_capture(stream_url)

        if not capture or not capture.isOpened():
            self._set_status(STREAM_STATUS_ERROR, "Unable to open stream.")
            self.logger.error("Failed to open stream.")
            if capture:
                capture.release()
            return False

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.resolution_width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.resolution_height)
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            try:
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                self.logger.debug("Capture backend does not support CAP_PROP_BUFFERSIZE.")
        self._capture = capture
        self.logger.info(
            "Connected to stream with target resolution %sx%s.",
            self.config.resolution_width,
            self.config.resolution_height,
        )
        return True

    def _read_frame(self) -> bool:
        """读取一帧并更新缓存；返回 False 表示需要重连。"""
        if self._capture is None:
            self._set_status(STREAM_STATUS_ERROR, "Capture is not initialized.")
            return False

        success, frame = self._capture.read()
        if not success or frame is None:
            self._read_failures += 1
            self._set_status(STREAM_STATUS_ERROR, "Failed to read frame from stream.")
            self.logger.warning(
                "Failed to read frame from stream. camera_id=%s failures=%s. Reconnecting.",
                self.config.id,
                self._read_failures,
            )
            self._release_capture()
            return False

        if not hasattr(frame, "size") or frame.size == 0:
            self._read_failures += 1
            self._set_status(STREAM_STATUS_ERROR, "Received empty frame from stream.")
            self.logger.warning(
                "Received empty frame from stream. camera_id=%s failures=%s. Reconnecting.",
                self.config.id,
                self._read_failures,
            )
            self._release_capture()
            return False

        with self._frame_lock:
            self._latest_frame = frame
            self._latest_frame_id += 1

        self._read_failures = 0
        self._frames_read += 1
        self._last_frame_at = time.strftime("%Y-%m-%d %H:%M:%S")
        if not self._first_frame_logged:
            self.logger.info(
                "first frame received. camera_id=%s shape=%s",
                self.config.id,
                getattr(frame, "shape", None),
            )
            self._first_frame_logged = True
        self._update_fps()
        return True

    def _open_capture(self, stream_url: str) -> cv2.VideoCapture:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = FFMPEG_CAPTURE_OPTIONS
        return cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)

    def _update_fps(self) -> None:
        now = time.monotonic()
        elapsed = now - self._fps_window_started_at
        if elapsed >= 1.0:
            self._last_fps = self._frames_read / elapsed
            self._frames_read = 0
            self._fps_window_started_at = now

    def _handle_reconnect_wait(self, reason: str) -> bool:
        self._reconnect_attempts += 1
        max_attempts = self.config.max_reconnect_attempts

        if max_attempts > 0 and self._reconnect_attempts > max_attempts:
            self._set_status(
                STREAM_STATUS_ERROR,
                f"Reconnect attempts exceeded limit: {reason}",
            )
            self.logger.error(
                "Reconnect attempts exceeded max limit (%s).", max_attempts
            )
            return False

        self._set_status(STREAM_STATUS_RECONNECTING, reason)
        self.logger.warning(
            "Camera stream reconnecting in %s seconds. Attempt %s. Reason: %s",
            self.config.retry_interval_seconds,
            self._reconnect_attempts,
            reason,
        )
        self._stop_event.wait(self.config.retry_interval_seconds)
        return not self._stop_event.is_set()

    def _set_status(self, status: str, error_message: str) -> None:
        with self._status_lock:
            self._status = status
            self._last_error = error_message

    def _release_capture(self) -> None:
        capture = self._capture
        self._capture = None
        if capture is not None:
            try:
                capture.release()
            except Exception as exc:
                self.logger.exception("Failed to release capture: %s", exc)

    def _requires_restart(
        self,
        previous_config: CameraConfig,
        next_config: CameraConfig,
    ) -> bool:
        return any(
            [
                previous_config.id != next_config.id,
                previous_config.rtsp_url.strip() != next_config.rtsp_url.strip(),
                previous_config.detection_rtsp_url.strip() != next_config.detection_rtsp_url.strip(),
                previous_config.source_type != next_config.source_type,
                previous_config.resolution_width != next_config.resolution_width,
                previous_config.resolution_height != next_config.resolution_height,
                previous_config.username != next_config.username,
                previous_config.password != next_config.password,
                previous_config.nvr_host != next_config.nvr_host,
                previous_config.nvr_port != next_config.nvr_port,
                previous_config.channel_no != next_config.channel_no,
            ]
        )


def mask_rtsp_url(url: str) -> str:
    try:
        parts = urlsplit(str(url or ""))
        if not parts.username:
            return str(url or "")

        hostname = parts.hostname or ""
        port_suffix = f":{parts.port}" if parts.port else ""
        netloc = f"{parts.username}:***@{hostname}{port_suffix}"
        return urlunsplit(
            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
        )
    except Exception:
        return "<invalid-rtsp-url>"
