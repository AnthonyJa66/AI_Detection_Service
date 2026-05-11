"""YOLO 模型加载与推理封装。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
from ultralytics import YOLO

from app.logger import get_logger


class ModelManager:
    """统一管理安全检测模型和抽烟检测模型。"""

    def __init__(
        self,
        project_root: str | None = None,
        confidence_threshold: float = 0.5,
        safety_confidence_threshold: float | None = None,
        smoking_confidence_threshold: float | None = None,
    ) -> None:
        self.logger = get_logger("video_monitor.model_manager")
        root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent.parent
        self._model_paths = {
            "ultra": root / "models" / "ultra.pt",
            "smoking": root / "models" / "best.pt",
        }
        default_confidence = float(confidence_threshold)
        self._confidence_thresholds = {
            "ultra": float(
                safety_confidence_threshold
                if safety_confidence_threshold is not None
                else default_confidence
            ),
            "smoking": float(
                smoking_confidence_threshold
                if smoking_confidence_threshold is not None
                else default_confidence
            ),
        }
        self._models: dict[str, YOLO | None] = {
            "ultra": None,
            "smoking": None,
        }
        self._load_attempted: dict[str, bool] = {
            "ultra": False,
            "smoking": False,
        }
        self._load_lock = threading.RLock()
        self._predict_locks: dict[str, threading.Lock] = {
            "ultra": threading.Lock(),
            "smoking": threading.Lock(),
        }

    def load_models(self) -> None:
        """预加载全部模型，适合在启动预热时调用。"""
        for model_name in self._models:
            self._get_model(model_name)

    def predict_all(self, frame: np.ndarray) -> dict[str, list[dict[str, Any]]]:
        outputs: dict[str, list[dict[str, Any]]] = {}
        for model_name in self._models:
            outputs[model_name] = self.predict(model_name, frame)
        return outputs

    def predict(self, model_name: str, frame: np.ndarray) -> list[dict[str, Any]]:
        """执行单模型推理并返回统一结构的检测结果。"""
        if model_name not in self._models:
            raise ValueError(f"Unsupported model name: {model_name}")
        if frame is None or not hasattr(frame, "shape") or frame.size == 0:
            self.logger.warning("Skipping inference for invalid frame on model %s.", model_name)
            return []

        try:
            model = self._get_model(model_name)
            if model is None:
                return []

            with self._predict_locks[model_name]:
                results = model(
                    frame,
                    conf=self._confidence_thresholds[model_name],
                    verbose=False,
                )

            # 保留现有调试输出，便于现场核对不同模型的置信度配置。
            if model_name == "ultra":
                print("safety conf:", self._confidence_thresholds["ultra"])
            if model_name == "smoking":
                print("smoking conf:", self._confidence_thresholds["smoking"])

            return self._parse_results(model_name, results)
        except Exception as exc:
            self.logger.exception("Inference failed for model %s: %s", model_name, exc)
            return []

    def _get_model(self, model_name: str) -> YOLO | None:
        """懒加载模型，失败后避免无限重复尝试。"""
        model = self._models.get(model_name)
        if model is not None:
            return model
        if self._load_attempted.get(model_name):
            return None

        with self._load_lock:
            model = self._models.get(model_name)
            if model is not None:
                return model
            if self._load_attempted.get(model_name):
                return None

            model_path = self._model_paths[model_name]
            self._load_attempted[model_name] = True
            if not model_path.exists():
                self.logger.error("Model file not found: %s", model_path)
                return None

            try:
                self.logger.info("Loading model %s from %s", model_name, model_path)
                loaded_model = YOLO(str(model_path))
                self._models[model_name] = loaded_model
                self.logger.info("Model %s loaded successfully.", model_name)
                return loaded_model
            except Exception as exc:
                self.logger.exception("Failed to load model %s: %s", model_name, exc)
                return None

    def _parse_results(
        self,
        model_name: str,
        results: list[Any],
    ) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            names = getattr(result, "names", {})
            if boxes is None:
                continue

            cls_values = boxes.cls.tolist() if boxes.cls is not None else []
            conf_values = boxes.conf.tolist() if boxes.conf is not None else []
            xyxy_values = boxes.xyxy.tolist() if boxes.xyxy is not None else []

            for class_id, confidence, xyxy in zip(cls_values, conf_values, xyxy_values):
                raw_name = str(names.get(int(class_id), str(class_id)))
                parsed.append(
                    {
                        "raw_class_name": raw_name,
                        "confidence": float(confidence),
                        "bbox": [int(value) for value in xyxy],
                        "source_model": model_name,
                    }
                )

        return parsed
