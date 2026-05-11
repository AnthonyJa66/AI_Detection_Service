"""检测结果统计辅助函数。

这里的统计口径会被主界面卡片、叠框接口和部分报警汇总逻辑复用。
"""

from __future__ import annotations

from app.models import DetectionResult
from app.utils.label_utils import normalize_label_name


VIOLATION_COUNT_KEYS = ("no_helmet_count", "no_vest_count", "smoking_count")
SMOKING_PERSON_DISTANCE_SCALE = 0.6


def _person_detections(detection_result: DetectionResult):
    return [
        item
        for item in detection_result.detections
        if normalize_label_name(item.class_name) == "person" and len(item.bbox or []) == 4
    ]


def _smoking_detections(detection_result: DetectionResult):
    return [
        item
        for item in detection_result.detections
        if normalize_label_name(item.class_name) == "smoking" and len(item.bbox or []) == 4
    ]


def _bbox_center(bbox: list[int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((float(x1) + float(x2)) / 2, (float(y1) + float(y2)) / 2)


def _bbox_size(bbox: list[int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (abs(float(x2) - float(x1)), abs(float(y2) - float(y1)))


def _bbox_distance(left_bbox: list[int], right_bbox: list[int]) -> float:
    lx, ly = _bbox_center(left_bbox)
    rx, ry = _bbox_center(right_bbox)
    return ((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5


def _person_distance_threshold(person_bbox: list[int]) -> float:
    person_width, person_height = _bbox_size(person_bbox)
    return max(person_width, person_height) * SMOKING_PERSON_DISTANCE_SCALE


def valid_smoking_detections(detection_result: DetectionResult):
    """只保留靠近人体的抽烟检测结果。"""
    person_detections = _person_detections(detection_result)
    if not person_detections:
        return []

    valid_items = []
    for smoke in _smoking_detections(detection_result):
        nearest_person = min(
            person_detections,
            key=lambda person: _bbox_distance(smoke.bbox, person.bbox),
            default=None,
        )
        if nearest_person is None:
            continue
        if _bbox_distance(smoke.bbox, nearest_person.bbox) <= _person_distance_threshold(nearest_person.bbox):
            valid_items.append(smoke)
    return valid_items


def filtered_violation_detections(detection_result: DetectionResult):
    """返回主界面叠框需要展示的违规检测结果。"""
    valid_smoking = {id(item): item for item in valid_smoking_detections(detection_result)}
    filtered_items = []
    for item in detection_result.detections:
        normalized_name = normalize_label_name(item.class_name)
        if normalized_name == "smoking":
            if id(item) in valid_smoking:
                filtered_items.append(item)
            continue
        if normalized_name in {"no_helmet", "no_vest"}:
            filtered_items.append(item)
    return filtered_items


def summarize_violation_counts(detection_result: DetectionResult) -> dict[str, int]:
    """返回主界面统计卡片使用的违规数量。"""
    detections = detection_result.detections
    normalized_names = [normalize_label_name(item.class_name) for item in detections]

    direct_no_helmet = sum(1 for name in normalized_names if name == "no_helmet")
    direct_no_vest = sum(1 for name in normalized_names if name == "no_vest")
    smoking_count = len(valid_smoking_detections(detection_result))

    if direct_no_helmet == 0:
        person_count = sum(1 for name in normalized_names if name == "person")
        has_helmet = any(name == "helmet" for name in normalized_names)
        if person_count > 0 and not has_helmet:
            direct_no_helmet = person_count

    if direct_no_vest == 0:
        person_count = sum(1 for name in normalized_names if name == "person")
        has_vest = any(name == "vest" for name in normalized_names)
        if person_count > 0 and not has_vest:
            direct_no_vest = person_count

    return {
        "no_helmet_count": direct_no_helmet,
        "no_vest_count": direct_no_vest,
        "smoking_count": smoking_count,
    }
