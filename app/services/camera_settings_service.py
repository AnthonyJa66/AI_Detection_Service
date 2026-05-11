"""settings.json 中摄像头配置的读写服务。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.config_loader import (
    ConfigError,
    load_settings,
    project_root,
    validate_settings_data,
)
from app.logger import get_logger


CAMERA_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
SOURCE_TYPE_RTSP_CAMERA = "rtsp_camera"
SOURCE_TYPE_NVR_RTSP = "nvr_rtsp"
SUPPORTED_SOURCE_TYPES = {
    SOURCE_TYPE_RTSP_CAMERA,
    SOURCE_TYPE_NVR_RTSP,
}


class CameraSettingsService:
    """负责摄像头配置的增删改查与落盘。"""

    def __init__(self, settings_path: str | None = None) -> None:
        self.logger = get_logger("video_monitor.camera_settings")
        self.settings_path = Path(settings_path) if settings_path else project_root() / "settings.json"

    def load_raw_settings(self) -> dict[str, Any]:
        with self.settings_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def list_cameras(self) -> list[dict[str, Any]]:
        settings = load_settings(str(self.settings_path))
        return settings.get("cameras", [])

    def get_camera(self, camera_id: str) -> dict[str, Any] | None:
        for camera in self.list_cameras():
            if camera["id"] == camera_id:
                return camera
        return None

    def add_camera(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_settings = self.load_raw_settings()
        normalized_camera = self.validate_camera_payload(payload)

        raw_cameras = raw_settings.get("cameras", [])
        if any(self._camera_id(camera) == normalized_camera["camera_id"] for camera in raw_cameras):
            raise ConfigError(f"摄像头已存在：{normalized_camera['camera_id']}")

        raw_cameras.append(normalized_camera)
        raw_settings["cameras"] = raw_cameras
        self._write_settings(raw_settings)
        return load_settings(str(self.settings_path))

    def update_camera(self, original_camera_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raw_settings = self.load_raw_settings()
        normalized_camera = self.validate_camera_payload(payload)

        raw_cameras = raw_settings.get("cameras", [])
        target_index = next(
            (index for index, camera in enumerate(raw_cameras) if self._camera_id(camera) == original_camera_id),
            None,
        )
        if target_index is None:
            raise ConfigError(f"摄像头不存在：{original_camera_id}")

        if normalized_camera["camera_id"] != original_camera_id:
            if any(
                self._camera_id(camera) == normalized_camera["camera_id"]
                for index, camera in enumerate(raw_cameras)
                if index != target_index
            ):
                raise ConfigError(f"摄像头已存在：{normalized_camera['camera_id']}")

        raw_cameras[target_index] = normalized_camera
        raw_settings["cameras"] = raw_cameras
        self._write_settings(raw_settings)
        return load_settings(str(self.settings_path))

    def delete_camera(self, camera_id: str) -> dict[str, Any]:
        raw_settings = self.load_raw_settings()
        raw_cameras = raw_settings.get("cameras", [])
        filtered_cameras = [
            camera for camera in raw_cameras if self._camera_id(camera) != camera_id
        ]
        if len(filtered_cameras) == len(raw_cameras):
            raise ConfigError(f"摄像头不存在：{camera_id}")

        raw_settings["cameras"] = filtered_cameras
        self._write_settings(raw_settings)
        return load_settings(str(self.settings_path))

    def toggle_camera(self, camera_id: str) -> dict[str, Any]:
        raw_settings = self.load_raw_settings()
        raw_cameras = raw_settings.get("cameras", [])
        found = False
        for camera in raw_cameras:
            if self._camera_id(camera) == camera_id:
                camera["enabled"] = not bool(camera.get("enabled", False))
                found = True
                break

        if not found:
            raise ConfigError(f"摄像头不存在：{camera_id}")

        raw_settings["cameras"] = raw_cameras
        self._write_settings(raw_settings)
        return load_settings(str(self.settings_path))

    def validate_camera_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """校验表单输入并转换为 settings.json 所需结构。"""
        camera_id = str(payload.get("camera_id", "")).strip()
        if not camera_id:
            raise ConfigError("摄像头 ID 不能为空。")
        if not CAMERA_ID_PATTERN.match(camera_id):
            raise ConfigError("摄像头 ID 只能包含字母、数字、下划线和连字符。")

        name = str(payload.get("name", "")).strip()
        if not name:
            raise ConfigError("摄像头名称不能为空。")

        source_type = str(payload.get("source_type", SOURCE_TYPE_RTSP_CAMERA)).strip()
        if source_type not in SUPPORTED_SOURCE_TYPES:
            raise ConfigError("视频源类型不支持。")

        rtsp_url = str(payload.get("rtsp_url", "")).strip()
        if not rtsp_url:
            raise ConfigError("RTSP URL 不能为空。")
        if not rtsp_url.lower().startswith("rtsp://"):
            raise ConfigError("RTSP URL 必须以 rtsp:// 开头。")

        try:
            width = int(payload.get("resolution_width", 0))
            height = int(payload.get("resolution_height", 0))
            fps_target = int(payload.get("fps_target", 0))
            retry_interval_seconds = int(payload.get("retry_interval_seconds", 0))
            max_reconnect_attempts = int(payload.get("max_reconnect_attempts", 0))
            nvr_port = int(payload.get("nvr_port", 554) or 554)
        except (TypeError, ValueError) as exc:
            raise ConfigError("摄像头数字参数格式不正确。") from exc

        if width <= 0 or height <= 0:
            raise ConfigError("分辨率宽度和高度必须大于 0。")
        if fps_target <= 0:
            raise ConfigError("目标 FPS 必须大于 0。")
        if retry_interval_seconds <= 0:
            raise ConfigError("重连间隔必须大于 0。")
        if max_reconnect_attempts < 0:
            raise ConfigError("最大重连次数不能小于 0。")
        if nvr_port <= 0:
            raise ConfigError("NVR 端口必须大于 0。")

        location = str(payload.get("location", "")).strip()
        enabled = bool(payload.get("enabled"))
        nvr_name = str(payload.get("nvr_name", "")).strip()
        nvr_host = str(payload.get("nvr_host", "")).strip()
        channel_no = str(payload.get("channel_no", "")).strip()
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", "")).strip()

        return {
            "camera_id": camera_id,
            "name": name,
            "source_type": source_type,
            "rtsp_url": rtsp_url,
            "enabled": enabled,
            "fps_target": fps_target,
            "retry_interval_seconds": retry_interval_seconds,
            "max_reconnect_attempts": max_reconnect_attempts,
            "resolution": {
                "width": width,
                "height": height,
            },
            "location": location,
            "nvr_name": nvr_name,
            "nvr_host": nvr_host,
            "nvr_port": nvr_port,
            "channel_no": channel_no,
            "username": username,
            "password": password,
        }

    def _write_settings(self, raw_settings: dict[str, Any]) -> None:
        validate_settings_data(raw_settings)
        temp_path = self.settings_path.with_suffix(".json.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(raw_settings, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temp_path.replace(self.settings_path)
        self.logger.info("settings.json updated successfully.")

    def _camera_id(self, camera: dict[str, Any]) -> str:
        return str(camera.get("camera_id") or camera.get("id") or "").strip()
