"""YOLOv8 inference service.

This module only wraps ultra.pt object detection inference. It does not perform
tracking, alarm handling, camera management, WebSocket pushing, or REST routing.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from ultralytics import YOLO

from app.schemas.detection_schema import DetectionResult


logger = logging.getLogger("ai_detection_service.inference_service")


class InferenceService:
    """Run YOLOv8 inference with a globally shared ultra.pt model."""

    _model: ClassVar[YOLO | None] = None
    _model_path: ClassVar[Path | None] = None
    _load_lock: ClassVar[threading.RLock] = threading.RLock()
    _predict_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(
        self,
        model_path: str | Path | None = None,
        confidence_threshold: float = 0.5,
    ) -> None:
        project_root = Path(__file__).resolve().parent.parent.parent
        self.model_path = Path(model_path) if model_path else project_root / "models" / "ultra.pt"
        self.confidence_threshold = float(confidence_threshold)
        self.logger = logger

    def predict(self, frame: np.ndarray) -> list[DetectionResult]:
        """Run YOLOv8 inference on one OpenCV frame."""

        if frame is None or not hasattr(frame, "shape") or frame.size == 0:
            self.logger.warning("Skipping inference for invalid OpenCV frame.")
            return []

        model = self._get_model(self.model_path)
        started_at = time.perf_counter()

        with self._predict_lock:
            raw_results = model(
                frame,
                conf=self.confidence_threshold,
                verbose=False,
            )

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        detections = self._parse_results(raw_results)
        self.logger.info(
            "YOLO inference completed. model=%s detections=%s elapsed_ms=%.2f",
            self.model_path,
            len(detections),
            elapsed_ms,
        )
        return detections

    @classmethod
    def _get_model(cls, model_path: Path) -> YOLO:
        resolved_model_path = model_path.resolve()

        with cls._load_lock:
            if cls._model is not None and cls._model_path == resolved_model_path:
                return cls._model

            if not resolved_model_path.exists():
                logger.error("YOLO model file not found: %s", resolved_model_path)
                raise FileNotFoundError(f"YOLO model file not found: {resolved_model_path}")

            logger.info("Loading YOLO model from %s", resolved_model_path)
            cls._model = YOLO(str(resolved_model_path))
            cls._model_path = resolved_model_path
            logger.info("YOLO model loaded successfully from %s", resolved_model_path)
            return cls._model

    def _parse_results(self, raw_results: list[Any]) -> list[DetectionResult]:
        detections: list[DetectionResult] = []

        for result in raw_results:
            boxes = getattr(result, "boxes", None)
            names = getattr(result, "names", {}) or {}
            if boxes is None:
                continue

            class_ids = boxes.cls.tolist() if boxes.cls is not None else []
            confidences = boxes.conf.tolist() if boxes.conf is not None else []
            bboxes = boxes.xyxy.tolist() if boxes.xyxy is not None else []

            for class_id, confidence, bbox in zip(class_ids, confidences, bboxes):
                normalized_class_id = int(class_id)
                detections.append(
                    DetectionResult(
                        class_id=normalized_class_id,
                        class_name=str(names.get(normalized_class_id, normalized_class_id)),
                        confidence=float(confidence),
                        bbox=[int(value) for value in bbox],
                    )
                )

        return detections
