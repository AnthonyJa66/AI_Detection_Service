"""违规规则引擎。

负责把逐帧检测结果整理成更稳定的违规状态事件，避免单帧抖动直接触发报警。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.logger import get_logger
from app.models import DetectionResult
from app.models.violation_event import ViolationEvent


RULE_CONFIDENCE_INFERRED = 1.0
DEFAULT_CONFIRM_COUNTS = {
    "no_helmet": 2,
    "no_vest": 2,
    "smoking": 3,
}
SUPPORTED_VIOLATION_TYPES = ("no_helmet", "no_vest", "smoking")
REQUIRED_CONFIRM_HITS = 3
SMOKING_PERSON_DISTANCE_SCALE = 0.6
ALARM_COOLDOWN_SECONDS = 5


@dataclass(slots=True)
class CameraRuleState:
    """单路摄像头的报警状态。

    RuleEngine 会被多路摄像头共享，如果这里不按 camera_id 隔离，
    一路视频的稳定计数和冷却时间就会把另一路的报警状态冲掉。
    """

    prev_state: tuple[bool, bool, bool] | None = None
    stable_count: int = 0
    last_alarm_state: tuple[bool, bool, bool] | None = None
    last_alarm_time: float = 0.0


def build_violation_event(result):
    counts = result["counts"]
    state = (
        counts["no_helmet"] > 0,
        counts["no_vest"] > 0,
        counts["smoking"] > 0,
    )

    violations = []

    if counts["no_helmet"] > 0:
        violations.append("无安全帽")

    if counts["no_vest"] > 0:
        violations.append("无反光背心")

    if counts["smoking"] > 0:
        violations.append("抽烟")

    if not violations:
        return None

    return {
        "camera_id": result["camera_id"],
        "timestamp": result["timestamp"],
        "state": state,
        "alarm_type": " / ".join(violations),
    }


class RuleEngine:
    """根据检测结果维护违规状态，并决定是否生成报警事件。"""

    def __init__(
        self,
        confirm_counts: dict[str, int] | None = None,
        clear_count: int | None = None,
        session_end_grace_seconds: float | None = None,
        enable_reminder_events: bool | None = None,
        reminder_interval_seconds: float | None = None,
    ) -> None:
        self.logger = get_logger("video_monitor.rule_engine")
        confirm_counts = confirm_counts or dict(DEFAULT_CONFIRM_COUNTS)
        self.confirm_counts = {
            violation_type: max(
                1,
                int(confirm_counts.get(violation_type, DEFAULT_CONFIRM_COUNTS[violation_type])),
            )
            for violation_type in SUPPORTED_VIOLATION_TYPES
        }
        self.required_confirm_hits = REQUIRED_CONFIRM_HITS
        self._camera_states: dict[str, CameraRuleState] = {}
        self._state_lock = threading.Lock()

    def evaluate(self, result):
        """对当前状态做去抖和冷却判断，返回报警事件或 None。"""
        counts = result["counts"]
        camera_id = str(result.get("camera_id") or "")
        state = (
            counts["no_helmet"] > 0,
            counts["no_vest"] > 0,
            counts["smoking"] > 0,
        )
        now = float(result["timestamp"] or 0)

        with self._state_lock:
            camera_state = self._camera_states.setdefault(camera_id, CameraRuleState())

            if state == camera_state.prev_state:
                camera_state.stable_count += 1
            else:
                camera_state.prev_state = state
                camera_state.stable_count = 1

            if camera_state.stable_count < self.required_confirm_hits:
                return None

            if state == (False, False, False):
                camera_state.last_alarm_state = None
                return None

            if now - camera_state.last_alarm_time < ALARM_COOLDOWN_SECONDS:
                return None

            if state == camera_state.last_alarm_state:
                return None

            event = build_violation_event(result)
            if event is None:
                return None

            camera_state.last_alarm_state = state
            camera_state.last_alarm_time = now
            return event

    def build_result(self, detection_result: DetectionResult) -> dict[str, object]:
        """把 DetectionResult 转成规则引擎内部使用的结构。"""
        return {
            "camera_id": detection_result.camera_id,
            "timestamp": self._normalize_timestamp(detection_result.timestamp),
            "counts": self._build_current_state(detection_result),
        }

    def process(self, detection_result: DetectionResult) -> list[ViolationEvent]:
        result = self.build_result(detection_result)
        current_timestamp = float(result["timestamp"])
        current_state = dict(result["counts"])
        event = self.evaluate(result)
        if event is None:
            return []

        violation_types = self._resolve_violation_types(current_state)
        return [
            self._build_event(
                camera_id=detection_result.camera_id,
                current_timestamp=current_timestamp,
                detection_result=detection_result,
                current_state=current_state,
                violation_types=violation_types,
                alarm_type=str(event["alarm_type"]),
            )
        ]

    def reset(self, camera_id: str | None = None) -> None:
        """清理规则状态。

        camera_id 为空时清空全部；传入具体摄像头时只清这一路，避免误伤其他流。
        """
        with self._state_lock:
            if camera_id is None:
                self._camera_states.clear()
                return
            self._camera_states.pop(str(camera_id), None)

    def _build_current_state(self, detection_result: DetectionResult) -> dict[str, int]:
        """构建当前违规计数。

        抽烟计数会先做“靠近人体”过滤，避免远处高亮区域被直接算作抽烟。
        """
        detections = detection_result.detections
        current_state = {violation_type: 0 for violation_type in SUPPORTED_VIOLATION_TYPES}

        person_detections = self._person_detections(detections)
        valid_smoking = self._match_smoking_detections(detections, person_detections)
        current_state["smoking"] = len(valid_smoking)

        # 安全帽/反光背心违规的前提必须先检测到人。
        # 这样可以避免画面无人时，模型偶发打出 no_helmet / no_vest 框就直接误报。
        if not person_detections:
            return current_state

        direct_no_helmet_detections = [
            detection for detection in detections if detection.class_name == "no_helmet"
        ]
        direct_no_vest_detections = [
            detection for detection in detections if detection.class_name == "no_vest"
        ]
        has_helmet = any(detection.class_name == "helmet" for detection in detections)
        has_vest = any(detection.class_name == "vest" for detection in detections)

        if direct_no_helmet_detections:
            current_state["no_helmet"] = len(direct_no_helmet_detections)
        elif not has_helmet:
            current_state["no_helmet"] = len(person_detections)

        if direct_no_vest_detections:
            current_state["no_vest"] = len(direct_no_vest_detections)
        elif not has_vest:
            current_state["no_vest"] = len(person_detections)

        return current_state

    def _person_detections(self, detections):
        return [detection for detection in detections if detection.class_name == "person"]

    def _smoking_detections(self, detections):
        return [detection for detection in detections if detection.class_name == "smoking"]

    def _match_smoking_detections(self, detections, person_detections=None):
        """抽烟框只归属最近的人体，未匹配到人体则直接丢弃。"""
        people = person_detections or self._person_detections(detections)
        if not people:
            return []

        valid_smoking = []
        for smoke in self._smoking_detections(detections):
            nearest_person = self._find_nearest_person(smoke.bbox, people)
            if nearest_person and self._is_near(smoke.bbox, nearest_person.bbox):
                valid_smoking.append(smoke)
        return valid_smoking

    def _find_nearest_person(self, smoke_bbox: list[int], person_detections):
        nearest_person = None
        nearest_distance = float("inf")
        for person in person_detections:
            distance = self._bbox_distance(smoke_bbox, person.bbox)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_person = person
        return nearest_person

    def _is_near(self, smoke_bbox: list[int], person_bbox: list[int]) -> bool:
        distance = self._bbox_distance(smoke_bbox, person_bbox)
        threshold = self._person_distance_threshold(person_bbox)
        return distance <= threshold

    def _bbox_center(self, bbox: list[int]) -> tuple[float, float]:
        x1, y1, x2, y2 = bbox
        return ((float(x1) + float(x2)) / 2, (float(y1) + float(y2)) / 2)

    def _bbox_distance(self, left_bbox: list[int], right_bbox: list[int]) -> float:
        lx, ly = self._bbox_center(left_bbox)
        rx, ry = self._bbox_center(right_bbox)
        return ((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5

    def _bbox_size(self, bbox: list[int]) -> tuple[float, float]:
        x1, y1, x2, y2 = bbox
        return (abs(float(x2) - float(x1)), abs(float(y2) - float(y1)))

    def _person_distance_threshold(self, person_bbox: list[int]) -> float:
        person_width, person_height = self._bbox_size(person_bbox)
        return max(person_width, person_height) * SMOKING_PERSON_DISTANCE_SCALE

    def _resolve_violation_types(self, current_state: dict[str, int]) -> list[str]:
        return [
            violation_type
            for violation_type in SUPPORTED_VIOLATION_TYPES
            if int(current_state.get(violation_type, 0)) > 0
        ]

    def _build_event(
        self,
        camera_id: str,
        current_timestamp: float,
        detection_result: DetectionResult,
        current_state: dict[str, int],
        violation_types: list[str],
        alarm_type: str,
    ) -> ViolationEvent:
        highest_confidence = self._resolve_event_confidence(detection_result, violation_types)
        snapshot_bbox = self._resolve_snapshot_bbox(detection_result, violation_types)

        return ViolationEvent(
            event_id=str(uuid4()),
            camera_id=camera_id,
            violation_type=alarm_type,
            timestamp=self._timestamp_to_iso(current_timestamp),
            confidence=highest_confidence,
            snapshot_bbox=snapshot_bbox,
            meta={
                "event_kind": "state_change",
                "is_active": True,
                "violation_count": int(sum(current_state.values())),
                "alarm_type": alarm_type,
                "violation_types": violation_types,
                "violation_counts": dict(current_state),
                "current_state": {
                    violation_type: int(current_state.get(violation_type, 0))
                    for violation_type in SUPPORTED_VIOLATION_TYPES
                },
                "frame_width": detection_result.frame_width,
                "frame_height": detection_result.frame_height,
            },
        )

    def _resolve_event_confidence(
        self,
        detection_result: DetectionResult,
        violation_types: list[str],
    ) -> float:
        matched_detections = self._resolve_event_detections(detection_result, violation_types)
        matched_confidences = [float(detection.confidence) for detection in matched_detections]
        if matched_confidences:
            return max(matched_confidences)
        return RULE_CONFIDENCE_INFERRED

    def _resolve_snapshot_bbox(
        self,
        detection_result: DetectionResult,
        violation_types: list[str],
    ) -> list[int] | None:
        matched = [
            detection
            for detection in self._resolve_event_detections(detection_result, violation_types)
            if detection.bbox
        ]
        if matched:
            best = max(matched, key=lambda detection: float(detection.confidence))
            return list(best.bbox)

        person_detections = [
            detection for detection in detection_result.detections if detection.class_name == "person"
        ]
        if person_detections:
            return list(person_detections[0].bbox)
        return None

    def _resolve_event_detections(
        self,
        detection_result: DetectionResult,
        violation_types: list[str],
    ):
        matched = []
        if "smoking" in violation_types:
            matched.extend(self._match_smoking_detections(detection_result.detections))

        matched.extend(
            detection
            for detection in detection_result.detections
            if detection.class_name in violation_types and detection.class_name != "smoking"
        )
        return matched

    def _normalize_timestamp(self, timestamp: object) -> float:
        if isinstance(timestamp, (int, float)):
            return float(timestamp)

        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return timestamp.timestamp()

        if isinstance(timestamp, str) and timestamp:
            try:
                normalized = timestamp.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(normalized)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.timestamp()
            except ValueError:
                self.logger.warning("Failed to parse timestamp %s, using current time.", timestamp)

        return datetime.now(timezone.utc).timestamp()

    def _timestamp_to_iso(self, timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
