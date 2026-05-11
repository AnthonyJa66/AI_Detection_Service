"""检测流水线。

负责组合多模型推理结果，并在需要时绘制主界面/截图使用的叠框画面。
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.logger import get_logger
from app.models import DetectionItem, DetectionResult
from app.models.violation_event import ViolationEvent
from app.services.model_manager import ModelManager
from app.utils import (
    filtered_violation_detections,
    get_display_label,
    normalize_label_name,
)
from app.utils.annotation_style_utils import (
    ANNOTATION_FONT_SIZE,
    ANNOTATION_LINE_WIDTH,
    ANNOTATION_TEXT_BOX_HEIGHT,
    ANNOTATION_TEXT_PADDING_X,
    get_annotation_color_bgr,
)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - optional dependency fallback
    Image = None
    ImageDraw = None
    ImageFont = None

FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
)


class DetectionPipeline:
    """串联模型推理、结果归一化和画面标注。"""

    def __init__(self, model_manager: ModelManager | None = None) -> None:
        self.logger = get_logger("video_monitor.detection_pipeline")
        self.model_manager = model_manager or ModelManager()

    def detect(self, camera_id: str, frame: np.ndarray) -> DetectionResult:
        """对单帧执行检测并返回统一的 DetectionResult。"""
        if frame is None or not hasattr(frame, "shape") or len(frame.shape) < 2:
            self.logger.warning("Received invalid frame for camera %s.", camera_id)
            return DetectionResult.empty(camera_id, 0, 0)
        if not hasattr(frame, "size") or frame.size == 0:
            self.logger.warning("Received empty frame for camera %s.", camera_id)
            return DetectionResult.empty(camera_id, 0, 0)

        frame_height, frame_width = frame.shape[:2]
        empty_result = DetectionResult.empty(camera_id, frame_width, frame_height)

        try:
            model_outputs = self.model_manager.predict_all(frame)
            if not model_outputs:
                return empty_result
            detections = self._merge_detections(model_outputs)
            return DetectionResult(
                camera_id=camera_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                frame_width=frame_width,
                frame_height=frame_height,
                detections=detections,
            )
        except Exception as exc:
            self.logger.exception("Detection failed for camera %s: %s", camera_id, exc)
            return empty_result

    def annotate_frame(
        self,
        frame: np.ndarray,
        detection_result: DetectionResult,
        violation_events: list[ViolationEvent] | None = None,
    ) -> np.ndarray:
        """在画面上绘制违规框和中文标签。"""
        if frame is None or not hasattr(frame, "shape") or frame.size == 0:
            self.logger.warning("Cannot annotate invalid frame.")
            return frame

        if detection_result is None:
            return frame.copy()

        annotated_frame = frame.copy()
        text_specs: list[tuple[int, int, str, tuple[int, int, int]]] = []

        try:
            annotation_items = self._build_annotation_items(
                detection_result,
                violation_events=violation_events,
            )
            for item in annotation_items:
                x1, y1, x2, y2 = item["bbox"]
                color = get_annotation_color_bgr(item["type"])
                label = f"{get_display_label(item['type'])} {float(item['confidence']):.2f}"

                cv2.rectangle(
                    annotated_frame,
                    (x1, y1),
                    (x2, y2),
                    color,
                    ANNOTATION_LINE_WIDTH,
                )
                text_specs.append((x1, y1, label, color))

            if not text_specs:
                return frame.copy()
            annotated_frame = self._draw_detection_labels(annotated_frame, text_specs)
        except Exception as exc:
            self.logger.exception("Failed to annotate frame: %s", exc)

        return annotated_frame

    def _merge_detections(
        self,
        model_outputs: dict[str, list[dict[str, Any]]],
    ) -> list[DetectionItem]:
        """把不同模型的输出统一转换为 DetectionItem 列表。"""
        merged: list[DetectionItem] = []
        for model_name, detections in model_outputs.items():
            for detection in detections:
                try:
                    unified_class_name = self._normalize_class_name(
                        detection["raw_class_name"]
                    )
                    merged.append(
                        DetectionItem(
                            class_name=unified_class_name,
                            confidence=round(float(detection["confidence"]), 4),
                            bbox=self._clip_bbox(detection["bbox"]),
                            source_model=model_name,
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    self.logger.warning(
                        "Skipping malformed detection from model %s: %s",
                        model_name,
                        exc,
                    )
        return merged

    def _build_annotation_items(
        self,
        detection_result: DetectionResult,
        violation_events: list[ViolationEvent] | None = None,
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        seen_types: set[str] = set()

        for detection in filtered_violation_detections(detection_result):
            normalized_type = normalize_label_name(detection.class_name)
            bbox = list(detection.bbox or [])
            if len(bbox) != 4:
                continue
            items.append(
                {
                    "type": normalized_type,
                    "confidence": float(detection.confidence),
                    "bbox": [int(value) for value in bbox],
                }
            )
            seen_types.add(normalized_type)

        if not violation_events:
            return items

        for event in violation_events:
            bbox = list(event.snapshot_bbox or [])
            if len(bbox) != 4:
                continue

            violation_types = event.meta.get("violation_types") or []
            for violation_type in violation_types:
                normalized_type = normalize_label_name(str(violation_type))
                if normalized_type in seen_types:
                    continue
                items.append(
                    {
                        "type": normalized_type,
                        "confidence": float(event.confidence),
                        "bbox": [int(value) for value in bbox],
                    }
                )
                seen_types.add(normalized_type)

        return items

    def _normalize_class_name(self, raw_class_name: str) -> str:
        return normalize_label_name(raw_class_name)

    def _clip_bbox(self, bbox: list[int]) -> list[int]:
        if len(bbox) != 4:
            return [0, 0, 0, 0]

        x1, y1, x2, y2 = bbox
        return [
            max(0, int(x1)),
            max(0, int(y1)),
            max(0, int(x2)),
            max(0, int(y2)),
        ]

    def _draw_detection_labels(
        self,
        frame: np.ndarray,
        text_specs: list[tuple[int, int, str, tuple[int, int, int]]],
    ) -> np.ndarray:
        if not text_specs:
            return frame

        if Image is None or ImageDraw is None or ImageFont is None:
            return self._draw_labels_with_opencv(frame, text_specs)

        font = _load_chinese_font(ANNOTATION_FONT_SIZE)
        if font is None:
            return self._draw_labels_with_opencv(frame, text_specs)

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb_frame)
        drawer = ImageDraw.Draw(image)

        for x1, y1, label, color in text_specs:
            left = max(0, x1)
            top = max(0, y1 - 30)
            text_box = drawer.textbbox((left, top), label, font=font)
            padding_x = ANNOTATION_TEXT_PADDING_X
            padding_y = 3
            bg_left = max(0, text_box[0] - padding_x)
            bg_top = max(0, text_box[1] - padding_y)
            bg_right = min(image.width, text_box[2] + padding_x)
            bg_bottom = min(
                image.height,
                max(text_box[3] + padding_y, bg_top + ANNOTATION_TEXT_BOX_HEIGHT),
            )
            drawer.rectangle(
                (bg_left, bg_top, bg_right, bg_bottom),
                fill=(color[2], color[1], color[0]),
            )
            drawer.text(
                (bg_left + padding_x // 2, bg_top + padding_y // 2),
                label,
                font=font,
                fill=(255, 255, 255),
            )

        return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

    def _draw_labels_with_opencv(
        self,
        frame: np.ndarray,
        text_specs: list[tuple[int, int, str, tuple[int, int, int]]],
    ) -> np.ndarray:
        for x1, y1, label, color in text_specs:
            (text_width, text_height), baseline = cv2.getTextSize(
                label,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                1,
            )
            box_top = max(0, y1 - ANNOTATION_TEXT_BOX_HEIGHT)
            box_bottom = min(frame.shape[0], box_top + ANNOTATION_TEXT_BOX_HEIGHT)
            box_right = min(
                frame.shape[1],
                x1 + text_width + ANNOTATION_TEXT_PADDING_X * 2,
            )
            cv2.rectangle(
                frame,
                (x1, box_top),
                (box_right, box_bottom),
                color,
                thickness=-1,
            )
            cv2.putText(
                frame,
                label,
                (x1 + ANNOTATION_TEXT_PADDING_X, box_bottom - max(5, baseline)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
        return frame


@lru_cache(maxsize=4)
def _load_chinese_font(font_size: int):
    """优先加载系统中文字体，避免标签出现方块字。"""
    if ImageFont is None:
        return None

    for candidate in FONT_CANDIDATES:
        if not candidate.exists():
            continue
        try:
            return ImageFont.truetype(str(candidate), font_size)
        except OSError:
            continue
    return None
