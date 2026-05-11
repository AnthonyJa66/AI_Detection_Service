"""报警截图服务。

截图直接取检测侧最近的分析画面，文件名中带摄像头和违规类型，便于后续追溯。
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

import cv2

from app.logger import get_logger
from app.models.violation_event import ViolationEvent
from app.services.video_processor import VideoProcessor
from app.utils import get_display_label


INVALID_PATH_CHARS_PATTERN = re.compile(r'[\\/:*?"<>|]+')


class AlarmSnapshotService:
    """负责报警截图生成与落盘。"""

    def __init__(
        self,
        video_processor: VideoProcessor,
        snapshot_dir: str,
    ) -> None:
        self.logger = get_logger("video_monitor.snapshot_service")
        self.video_processor = video_processor
        self.snapshot_dir = Path(snapshot_dir)
        self._known_directories: set[Path] = set()
        self._dir_lock = threading.Lock()
        self._ensure_directory(self.snapshot_dir)

    def create_snapshot(self, events: list[ViolationEvent]) -> str | None:
        """按事件批次生成一张截图并返回相对路径。"""
        if not events:
            return None

        primary_event = events[0]
        frame = self.video_processor.build_alarm_snapshot_frame(
            primary_event.camera_id,
            events,
        )
        if frame is None:
            self.logger.warning(
                "No frame available for snapshot. camera_id=%s event_ids=%s",
                primary_event.camera_id,
                [event.event_id for event in events],
            )
            return None

        camera_name = self._resolve_camera_name(primary_event.camera_id)
        timestamp = self._parse_timestamp(primary_event.timestamp)
        date_folder = timestamp.strftime("%Y-%m-%d")
        time_text = timestamp.strftime("%Y%m%d_%H%M%S")
        violation_text = self._build_violation_group_name(events)

        safe_camera_dir = self._sanitize_component(camera_name, fallback=primary_event.camera_id)
        safe_camera_file = self._sanitize_component(camera_name, fallback=primary_event.camera_id)
        safe_violation_text = self._sanitize_component(violation_text, fallback="报警")

        target_dir = self.snapshot_dir / date_folder / safe_camera_dir
        if not self._ensure_directory(target_dir):
            return None

        # 文件名规则：摄像头_违规类型_时间，重复时自动追加序号。
        base_filename = f"{safe_camera_file}_{safe_violation_text}_{time_text}"
        file_path = self._allocate_file_path(target_dir, base_filename)

        try:
            success, encoded = cv2.imencode(".jpg", frame)
            if not success:
                self.logger.error(
                    "Failed to encode snapshot image. camera_id=%s event_ids=%s",
                    primary_event.camera_id,
                    [event.event_id for event in events],
                )
                return None

            file_path.write_bytes(encoded.tobytes())
            return file_path.relative_to(self.snapshot_dir).as_posix()
        except Exception as exc:
            self.logger.exception(
                "Failed to save snapshot for events %s: %s",
                [event.event_id for event in events],
                exc,
            )
            return None

    def _resolve_camera_name(self, camera_id: str) -> str:
        settings = getattr(self.video_processor, "settings", {}) or {}
        for camera in settings.get("cameras", []):
            if str(camera.get("id")) == camera_id or str(camera.get("camera_id")) == camera_id:
                camera_name = str(camera.get("name", "")).strip()
                if camera_name:
                    return camera_name
        return camera_id

    def _build_violation_group_name(self, events: list[ViolationEvent]) -> str:
        alarm_type = str(events[0].meta.get("alarm_type") or "").strip()
        if alarm_type:
            names = [name.strip() for name in alarm_type.split("/") if name.strip()]
            return "_".join(names)

        violation_names = {
            get_display_label(event.violation_type)
            for event in events
        }
        sorted_names = sorted(name for name in violation_names if name)
        return "_".join(sorted_names) if sorted_names else "报警"

    def _parse_timestamp(self, value: str) -> datetime:
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is not None:
                return parsed.astimezone()
            return parsed
        except ValueError:
            return datetime.now().astimezone()

    def _sanitize_component(self, value: str, fallback: str) -> str:
        cleaned = INVALID_PATH_CHARS_PATTERN.sub("", value or "")
        cleaned = " ".join(cleaned.strip().split())
        cleaned = cleaned[:60].strip(" .")
        if not cleaned:
            cleaned = fallback
        return cleaned

    def _allocate_file_path(self, target_dir: Path, base_filename: str) -> Path:
        candidate = target_dir / f"{base_filename}.jpg"
        if not candidate.exists():
            return candidate

        suffix = 1
        while True:
            candidate = target_dir / f"{base_filename}_{suffix:02d}.jpg"
            if not candidate.exists():
                return candidate
            suffix += 1

    def _ensure_directory(self, directory: Path) -> bool:
        with self._dir_lock:
            if directory in self._known_directories:
                return True

            try:
                directory.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                self.logger.exception("Failed to create snapshot directory %s: %s", directory, exc)
                return False

            self._known_directories.add(directory)
            return True
