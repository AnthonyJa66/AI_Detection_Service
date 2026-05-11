"""摄像头流实例管理。

CameraManager 负责把 settings.json 中的多路摄像头配置映射成 CameraStream 实例，
并对外提供统一的启动、停止、取帧和状态查询接口。
"""

import threading
from typing import Any

from app.logger import get_logger
from app.services.camera_stream import CameraConfig, CameraStream
from app.services.stream_factory import StreamFactory


class CameraManager:
    """管理所有 CameraStream 的生命周期。"""

    def __init__(self, stream_factory: StreamFactory | None = None) -> None:
        self.logger = get_logger("video_monitor.camera_manager")
        self._lock = threading.RLock()
        self._stream_factory = stream_factory or StreamFactory()
        self._streams: dict[str, CameraStream] = {}

    def load_from_settings(self, settings: dict[str, Any]) -> None:
        """按配置热更新摄像头集合。"""
        cameras = settings.get("cameras", [])
        next_configs = {
            config.id: config
            for config in (CameraConfig.from_dict(camera_data) for camera_data in cameras)
        }

        with self._lock:
            existing_ids = set(self._streams.keys())
            next_ids = set(next_configs.keys())

            removed_ids = sorted(existing_ids - next_ids)
            added_ids = sorted(next_ids - existing_ids)
            shared_ids = sorted(existing_ids & next_ids)

        for camera_id in removed_ids:
            self.remove_camera(camera_id)

        for camera_id in shared_ids:
            self._apply_hot_update(next_configs[camera_id])

        for camera_id in added_ids:
            self.add_camera(next_configs[camera_id])

        self.logger.info(
            "Loaded camera streams from settings. total=%s added=%s updated=%s removed=%s",
            len(next_configs),
            len(added_ids),
            len(shared_ids),
            len(removed_ids),
        )

    def start_all(self) -> None:
        with self._lock:
            streams = list(self._streams.items())

        for camera_id, stream in streams:
            if not stream.config.enabled:
                self.logger.info("Skipping disabled camera: %s", camera_id)
                continue
            try:
                stream.start()
            except Exception as exc:
                self.logger.exception(
                    "Failed to start camera stream %s: %s", camera_id, exc
                )

    def stop_all(self) -> None:
        with self._lock:
            streams = list(self._streams.items())

        for camera_id, stream in streams:
            try:
                stream.stop()
            except Exception as exc:
                self.logger.exception(
                    "Failed to stop camera stream %s: %s", camera_id, exc
                )

    def get_frame(self, camera_id: str, copy: bool = True):
        with self._lock:
            stream = self._streams.get(camera_id)

        if stream is None:
            self.logger.warning("Camera %s not found when requesting frame.", camera_id)
            return None

        return stream.get_frame(copy=copy)

    def get_frame_packet(self, camera_id: str, copy: bool = True) -> dict[str, Any] | None:
        """返回带 frame_id 的最新帧，用于 MJPEG 推流和去重。"""
        with self._lock:
            stream = self._streams.get(camera_id)

        if stream is None:
            self.logger.warning("Camera %s not found when requesting frame packet.", camera_id)
            return None

        return stream.get_frame_packet(copy=copy)

    def has_camera(self, camera_id: str) -> bool:
        with self._lock:
            return camera_id in self._streams

    def get_status(self, camera_id: str) -> dict[str, Any] | None:
        with self._lock:
            stream = self._streams.get(camera_id)

        if stream is None:
            self.logger.warning("Camera %s not found when requesting status.", camera_id)
            return None

        return stream.get_status()

    def get_all_status(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            streams = list(self._streams.items())

        return {
            camera_id: stream.get_status()
            for camera_id, stream in streams
        }

    def add_camera(self, camera_config: CameraConfig) -> None:
        with self._lock:
            if camera_config.id in self._streams:
                raise ValueError(f"Camera already exists: {camera_config.id}")

            stream = self._stream_factory.create(camera_config)
            self._streams[camera_config.id] = stream

        self.logger.info("Added camera: %s", camera_config.id)
        if camera_config.enabled:
            stream.start()

    def update_camera(
        self,
        camera_config: CameraConfig,
        previous_camera_id: str | None = None,
    ) -> None:
        target_camera_id = previous_camera_id or camera_config.id
        if previous_camera_id and previous_camera_id != camera_config.id and self.has_camera(camera_config.id):
            raise ValueError(f"Camera already exists: {camera_config.id}")
        if previous_camera_id and previous_camera_id != camera_config.id:
            self.remove_camera(target_camera_id)
            self.add_camera(camera_config)
            return
        self._apply_hot_update(camera_config)

    def replace_settings(self, settings: dict[str, Any]) -> None:
        self.load_from_settings(settings)

    def remove_camera(self, camera_id: str) -> bool:
        with self._lock:
            stream = self._streams.pop(camera_id, None)

        if stream is None:
            self.logger.warning("Camera %s not found when removing.", camera_id)
            return False

        try:
            stream.stop()
        except Exception as exc:
            self.logger.exception("Failed to stop camera %s: %s", camera_id, exc)
            return False

        self.logger.info("Removed camera: %s", camera_id)
        return True

    def get_camera_ids(self) -> list[str]:
        with self._lock:
            return list(self._streams.keys())

    def _apply_hot_update(self, camera_config: CameraConfig) -> None:
        """应用单路摄像头热更新。

        只有真正影响底层连接的配置变化才触发重启，避免无意义中断。
        """
        with self._lock:
            stream = self._streams.get(camera_config.id)

        if stream is None:
            self.add_camera(camera_config)
            return

        previous_enabled = bool(stream.config.enabled)
        requires_restart = stream.update_config(camera_config)

        if requires_restart:
            stream.stop()
            if camera_config.enabled:
                stream.start()
            return

        if previous_enabled and not camera_config.enabled:
            stream.stop()
            return

        if not previous_enabled and camera_config.enabled:
            stream.start()
