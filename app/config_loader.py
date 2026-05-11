"""配置加载与标准化模块。

负责读取 settings.json、校验关键字段，并把相对路径转换为项目绝对路径。
"""

import json
import logging
from pathlib import Path
from typing import Any

from app.models.video_source import (
    SOURCE_TYPE_RTSP_CAMERA,
    SUPPORTED_SOURCE_TYPES,
)


module_logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when application configuration is invalid."""


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def project_root() -> Path:
    return _project_root()


def validate_settings_data(settings: dict[str, Any]) -> None:
    """校验应用配置结构和关键字段取值。"""
    required_paths = [
        ("server", "host"),
        ("server", "port"),
        ("server", "debug"),
        ("paths", "snapshot_dir"),
        ("paths", "db_path"),
        ("logging", "level"),
        ("logging", "file"),
        ("detection", "detect_interval_seconds"),
        ("detection", "max_inference_workers"),
        ("alarm", "confirm_counts"),
        ("alarm", "clear_count"),
        ("alarm", "session_end_grace_seconds"),
        ("alarm", "enable_reminder_events"),
        ("alarm", "reminder_interval_seconds"),
    ]

    for section, key in required_paths:
        if section not in settings or key not in settings[section]:
            raise ConfigError(f"Missing required setting: {section}.{key}")

    detection_settings = settings["detection"]
    legacy_confidence = detection_settings.get("confidence")
    safety_confidence = detection_settings.get("safety_confidence", legacy_confidence)
    smoking_confidence = detection_settings.get("smoking_confidence", legacy_confidence)

    if safety_confidence is None or smoking_confidence is None:
        raise ConfigError(
            "Detection confidence must define confidence or both safety_confidence and smoking_confidence."
        )

    if not 0 <= float(safety_confidence) <= 1:
        raise ConfigError("Detection safety_confidence must be between 0 and 1.")

    if not 0 <= float(smoking_confidence) <= 1:
        raise ConfigError("Detection smoking_confidence must be between 0 and 1.")

    if float(settings["detection"]["detect_interval_seconds"]) <= 0:
        raise ConfigError("Detection detect_interval_seconds must be greater than 0.")

    if int(settings["detection"]["max_inference_workers"]) <= 0:
        raise ConfigError("Detection max_inference_workers must be greater than 0.")

    confirm_counts = settings["alarm"]["confirm_counts"]
    if not isinstance(confirm_counts, dict):
        raise ConfigError("Alarm confirm_counts must be an object.")

    for violation_type in ("no_helmet", "no_vest", "smoking"):
        if violation_type not in confirm_counts:
            raise ConfigError(f"Missing required alarm confirm count: {violation_type}")
        if int(confirm_counts[violation_type]) <= 0:
            raise ConfigError(f"Alarm confirm count must be greater than 0: {violation_type}")

    if int(settings["alarm"]["clear_count"]) <= 0:
        raise ConfigError("Alarm clear_count must be greater than 0.")

    if float(settings["alarm"]["session_end_grace_seconds"]) < 0:
        raise ConfigError("Alarm session_end_grace_seconds must be >= 0.")

    if float(settings["alarm"]["reminder_interval_seconds"]) <= 0:
        raise ConfigError("Alarm reminder_interval_seconds must be greater than 0.")

    cameras = settings.get("cameras")
    if not isinstance(cameras, list):
        raise ConfigError("Setting 'cameras' must be a list.")

    seen_camera_ids: set[str] = set()
    for camera in cameras:
        validate_camera_data(camera)
        camera_id = _get_camera_identifier(camera)
        if camera_id in seen_camera_ids:
            raise ConfigError(f"Duplicate camera id: {camera_id}")
        seen_camera_ids.add(camera_id)


def validate_camera_data(camera: dict[str, Any]) -> None:
    """校验单路摄像头配置是否合法。"""
    required_keys = [
        "name",
        "enabled",
        "fps_target",
        "retry_interval_seconds",
        "max_reconnect_attempts",
        "resolution",
    ]

    for key in required_keys:
        if key not in camera:
            raise ConfigError(f"Camera config missing required field: {key}")

    camera_id = _get_camera_identifier(camera)
    if not camera_id:
        raise ConfigError("Camera config missing required field: camera_id")

    if not isinstance(camera["resolution"], dict):
        raise ConfigError("Camera resolution must be an object.")

    for resolution_key in ("width", "height"):
        if resolution_key not in camera["resolution"]:
            raise ConfigError(
                f"Camera resolution missing required field: {resolution_key}"
            )

    if not isinstance(camera_id, str) or not camera_id.strip():
        raise ConfigError("Camera id must be a non-empty string.")

    source_type = str(camera.get("source_type") or SOURCE_TYPE_RTSP_CAMERA).strip()
    if source_type not in SUPPORTED_SOURCE_TYPES:
        raise ConfigError(f"Unsupported camera source_type: {source_type}")

    rtsp_url = str(camera.get("rtsp_url", "")).strip()
    if not rtsp_url:
        raise ConfigError("Camera rtsp_url must be a non-empty string.")

    if int(camera["fps_target"]) <= 0:
        raise ConfigError("Camera fps_target must be greater than 0.")

    if int(camera["retry_interval_seconds"]) <= 0:
        raise ConfigError("Camera retry_interval_seconds must be greater than 0.")

    if int(camera["max_reconnect_attempts"]) < 0:
        raise ConfigError("Camera max_reconnect_attempts must be >= 0.")

    if int(camera["resolution"]["width"]) <= 0 or int(camera["resolution"]["height"]) <= 0:
        raise ConfigError("Camera resolution width and height must be greater than 0.")

    nvr_port = int(camera.get("nvr_port", 554) or 554)
    if nvr_port <= 0:
        raise ConfigError("Camera nvr_port must be greater than 0.")


def _normalize_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """把原始配置转换为运行期配置。"""
    project_root = _project_root()

    normalized = dict(settings)
    normalized["project_root"] = str(project_root)

    paths = dict(settings["paths"])
    paths["snapshot_dir"] = str((project_root / paths["snapshot_dir"]).resolve())
    paths["db_path"] = str((project_root / paths["db_path"]).resolve())

    logging_config = dict(settings["logging"])
    logging_config["file"] = str((project_root / logging_config["file"]).resolve())

    detection_config = dict(settings["detection"])
    legacy_confidence = detection_config.get("confidence")
    if legacy_confidence is None:
        legacy_confidence = detection_config.get("safety_confidence")
    if legacy_confidence is None:
        legacy_confidence = detection_config.get("smoking_confidence")
    detection_config["confidence"] = float(legacy_confidence)
    detection_config["safety_confidence"] = float(
        detection_config.get("safety_confidence", detection_config["confidence"])
    )
    detection_config["smoking_confidence"] = float(
        detection_config.get("smoking_confidence", detection_config["confidence"])
    )
    detection_config["detect_interval_seconds"] = float(
        detection_config["detect_interval_seconds"]
    )
    detection_config["max_inference_workers"] = int(
        detection_config["max_inference_workers"]
    )

    alarm_config = dict(settings["alarm"])
    alarm_config["confirm_counts"] = {
        "no_helmet": int(alarm_config["confirm_counts"]["no_helmet"]),
        "no_vest": int(alarm_config["confirm_counts"]["no_vest"]),
        "smoking": int(alarm_config["confirm_counts"]["smoking"]),
    }
    alarm_config["clear_count"] = int(alarm_config["clear_count"])
    alarm_config["session_end_grace_seconds"] = float(
        alarm_config["session_end_grace_seconds"]
    )
    alarm_config["enable_reminder_events"] = bool(
        alarm_config["enable_reminder_events"]
    )
    alarm_config["reminder_interval_seconds"] = float(
        alarm_config["reminder_interval_seconds"]
    )
    display_settings = dict(settings.get("display", {}))
    normalized_display = {
        "display_detection_overlay": bool(
            display_settings.get("display_detection_overlay", False)
        )
    }

    normalized_cameras = []
    for camera in settings["cameras"]:
        camera_id = _get_camera_identifier(camera)
        normalized_camera = dict(camera)
        normalized_camera["id"] = camera_id
        normalized_camera["camera_id"] = camera_id
        normalized_camera["source_type"] = str(
            camera.get("source_type") or SOURCE_TYPE_RTSP_CAMERA
        )
        normalized_camera["rtsp_url"] = str(camera.get("rtsp_url", "")).strip()
        # detection_rtsp_url 为可选检测专用流，未配置时由 CameraStream 回退到 rtsp_url。
        normalized_camera["detection_rtsp_url"] = str(
            camera.get("detection_rtsp_url", "")
        ).strip()
        normalized_camera["resolution"] = {
            "width": int(camera["resolution"]["width"]),
            "height": int(camera["resolution"]["height"]),
        }
        normalized_camera["fps_target"] = int(camera["fps_target"])
        normalized_camera["retry_interval_seconds"] = int(
            camera["retry_interval_seconds"]
        )
        normalized_camera["max_reconnect_attempts"] = int(
            camera["max_reconnect_attempts"]
        )
        normalized_camera["enabled"] = bool(camera["enabled"])
        normalized_camera["location"] = str(camera.get("location", ""))
        normalized_camera["nvr_name"] = str(camera.get("nvr_name", ""))
        normalized_camera["nvr_host"] = str(camera.get("nvr_host", ""))
        normalized_camera["nvr_port"] = int(camera.get("nvr_port", 554) or 554)
        normalized_camera["channel_no"] = str(camera.get("channel_no", ""))
        normalized_camera["username"] = str(camera.get("username", ""))
        normalized_camera["password"] = str(camera.get("password", ""))
        normalized_cameras.append(normalized_camera)

    normalized["paths"] = paths
    normalized["logging"] = logging_config
    normalized["detection"] = detection_config
    normalized["alarm"] = alarm_config
    normalized["display"] = normalized_display
    normalized["cameras"] = normalized_cameras
    return normalized


def ensure_runtime_directories(settings: dict[str, Any]) -> None:
    """确保截图、日志、数据库目录在启动前已创建。"""
    Path(settings["paths"]["snapshot_dir"]).mkdir(parents=True, exist_ok=True)
    Path(settings["logging"]["file"]).parent.mkdir(parents=True, exist_ok=True)
    Path(settings["paths"]["db_path"]).parent.mkdir(parents=True, exist_ok=True)


def load_settings(config_path: str | None = None) -> dict[str, Any]:
    """读取、校验并返回运行期配置。"""
    path = Path(config_path) if config_path else _project_root() / "settings.json"

    try:
        module_logger.info("Loading settings from %s", path)
        with path.open("r", encoding="utf-8") as file:
            settings = json.load(file)
    except FileNotFoundError as exc:
        module_logger.exception("Settings file not found: %s", path)
        raise ConfigError(f"Settings file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        module_logger.exception("Settings file is not valid JSON: %s", path)
        raise ConfigError(f"Settings file is not valid JSON: {path}") from exc
    except OSError as exc:
        module_logger.exception("Failed to read settings file: %s", path)
        raise ConfigError(f"Failed to read settings file: {path}") from exc

    try:
        validate_settings_data(settings)
    except ConfigError:
        module_logger.exception("Settings validation failed.")
        raise
    except (TypeError, ValueError) as exc:
        module_logger.exception("Settings validation failed: %s", exc)
        raise ConfigError("Settings values are invalid.") from exc

    normalized_settings = _normalize_settings(settings)
    ensure_runtime_directories(normalized_settings)
    module_logger.info("Settings loaded successfully.")
    return normalized_settings


def _get_camera_identifier(camera: dict[str, Any]) -> str:
    return str(camera.get("camera_id") or camera.get("id") or "").strip()
