"""检测调度服务。

负责从 CameraManager 读取最新帧，按固定间隔提交给 DetectionPipeline 推理，
再把检测结果送入 RuleEngine 和 AlarmManager。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import numpy as np

from app.logger import get_logger
from app.models import DetectionResult
from app.models.violation_event import ViolationEvent
from app.services.alarm_manager import AlarmManager
from app.services.camera_manager import CameraManager
from app.services.detection_pipeline import DetectionPipeline
from app.services.model_manager import ModelManager
from app.services.rule_engine import RuleEngine


class StreamProcessor:
    """单路检测处理器。

    设计目标是“取最新帧做推理”，避免检测线程被旧帧堆积拖慢。
    """

    def __init__(
        self,
        camera_id: str,
        camera_manager: CameraManager,
        detection_pipeline: DetectionPipeline,
        rule_engine: RuleEngine | None,
        alarm_manager: AlarmManager | None,
        detect_interval_seconds: float,
    ) -> None:
        self.camera_id = camera_id
        self.camera_manager = camera_manager
        self.detection_pipeline = detection_pipeline
        self.rule_engine = rule_engine
        self.alarm_manager = alarm_manager
        self.detect_interval_seconds = max(0.05, float(detect_interval_seconds))
        self.logger = get_logger(f"video_monitor.processor.{camera_id}")
        self._lock = threading.Lock()
        self._latest_raw_frame: np.ndarray | None = None
        self._latest_analysis_frame: np.ndarray | None = None
        self._latest_detection = DetectionResult.empty(camera_id, 0, 0)
        self._last_detected_at = 0.0
        self._inflight = False

    def stop(self) -> None:
        with self._lock:
            self._latest_raw_frame = None
            self._latest_analysis_frame = None
            self._latest_detection = DetectionResult.empty(self.camera_id, 0, 0)
            self._inflight = False
            self._last_detected_at = 0.0

    def get_latest_display_frame(self, display_detection_overlay: bool) -> np.ndarray | None:
        """根据开关返回原始画面或已叠框画面。"""
        with self._lock:
            if display_detection_overlay and self._latest_analysis_frame is not None:
                return self._latest_analysis_frame.copy()
            if self._latest_raw_frame is not None:
                return self._latest_raw_frame.copy()
            if self._latest_analysis_frame is not None:
                return self._latest_analysis_frame.copy()
            return None

    def get_latest_snapshot_frame(self) -> np.ndarray | None:
        with self._lock:
            if self._latest_analysis_frame is not None:
                return self._latest_analysis_frame.copy()
            if self._latest_raw_frame is not None:
                return self._latest_raw_frame.copy()
            return None

    def get_latest_raw_frame(self) -> np.ndarray | None:
        with self._lock:
            if self._latest_raw_frame is not None:
                return self._latest_raw_frame.copy()
            return None

    def get_latest_detection(self) -> DetectionResult:
        with self._lock:
            return DetectionResult(
                camera_id=self._latest_detection.camera_id,
                timestamp=self._latest_detection.timestamp,
                frame_width=self._latest_detection.frame_width,
                frame_height=self._latest_detection.frame_height,
                detections=list(self._latest_detection.detections),
            )

    def try_schedule(self, now: float) -> bool:
        """控制单路摄像头的检测节流，避免重复提交推理任务。"""
        with self._lock:
            if self._inflight:
                return False
            if self._last_detected_at > 0 and (now - self._last_detected_at) < self.detect_interval_seconds:
                return False
            self._inflight = True
            return True

    def process_latest_frame(self) -> None:
        """读取最新帧并执行一次检测流水线。"""
        try:
            raw_frame = self.camera_manager.get_frame(self.camera_id, copy=False)
            if raw_frame is None:
                self.logger.debug("No frame available for camera %s.", self.camera_id)
                return

            if not hasattr(raw_frame, "size") or raw_frame.size == 0:
                self.logger.warning("Skipping invalid frame for camera %s.", self.camera_id)
                return

            detection_result = self.detection_pipeline.detect(
                self.camera_id,
                raw_frame,
            )

            raw_display_frame = raw_frame.copy()
            if detection_result.detections:
                analysis_frame = self.detection_pipeline.annotate_frame(
                    raw_frame,
                    detection_result,
                )
            else:
                analysis_frame = raw_display_frame.copy()

            with self._lock:
                self._latest_detection = detection_result
                self._latest_raw_frame = raw_display_frame
                self._latest_analysis_frame = analysis_frame

            self._handle_detection_result(detection_result)
        except Exception as exc:
            self.logger.exception("Stream processor failed for camera %s: %s", self.camera_id, exc)
        finally:
            with self._lock:
                self._last_detected_at = time.monotonic()
                self._inflight = False

    def _handle_detection_result(self, detection_result: DetectionResult) -> None:
        """把检测结果交给规则引擎和报警管理器。"""
        if self.rule_engine is None or self.alarm_manager is None:
            return

        try:
            events = self.rule_engine.process(detection_result)
        except Exception as exc:
            self.logger.exception(
                "RuleEngine failed for camera %s: %s",
                self.camera_id,
                exc,
            )
            return

        if not events:
            return

        try:
            self.alarm_manager.handle_events(events)
        except Exception as exc:
            self.logger.exception(
                "AlarmManager failed for camera %s: %s",
                self.camera_id,
                exc,
            )


class VideoProcessor:
    """检测任务调度器。"""

    def __init__(
        self,
        camera_manager: CameraManager,
        settings: dict[str, Any],
        detection_pipeline: DetectionPipeline | None = None,
        rule_engine: RuleEngine | None = None,
        alarm_manager: AlarmManager | None = None,
    ) -> None:
        self.logger = get_logger("video_monitor.video_processor")
        self.camera_manager = camera_manager
        self.settings = settings
        detection_settings = settings.get("detection", {})
        self.model_manager = ModelManager(
            project_root=settings.get("project_root"),
            confidence_threshold=detection_settings.get("confidence", 0.5),
            safety_confidence_threshold=detection_settings.get("safety_confidence"),
            smoking_confidence_threshold=detection_settings.get("smoking_confidence"),
        )
        self.detection_pipeline = detection_pipeline or DetectionPipeline(
            model_manager=self.model_manager
        )
        self.rule_engine = rule_engine
        self.alarm_manager = alarm_manager
        self.detect_interval_seconds = self._get_detect_interval_seconds(detection_settings)
        self.max_inference_workers = max(
            1,
            int(detection_settings.get("max_inference_workers", 1)),
        )
        self.display_detection_overlay = self._get_display_detection_overlay(settings)
        self._processors: dict[str, StreamProcessor] = {}
        self._lock = threading.RLock()
        self._scheduler_stop_event = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None

    def load_from_settings(self) -> None:
        """根据当前配置重建检测处理器集合。"""
        cameras = self.settings.get("cameras", [])
        with self._lock:
            self.stop_all()
            self._processors = {}
            for camera in cameras:
                camera_id = str(camera["id"])
                self._processors[camera_id] = StreamProcessor(
                    camera_id=camera_id,
                    camera_manager=self.camera_manager,
                    detection_pipeline=self.detection_pipeline,
                    rule_engine=self.rule_engine,
                    alarm_manager=self.alarm_manager,
                    detect_interval_seconds=self.detect_interval_seconds,
                )
        self.logger.info("Loaded %s stream processors.", len(cameras))

    def start_all(self) -> None:
        """启动统一调度线程和推理线程池。"""
        with self._lock:
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                self.logger.warning("Video processor scheduler is already running.")
                return

            self._scheduler_stop_event.clear()
            self._executor = ThreadPoolExecutor(
                max_workers=self.max_inference_workers,
                thread_name_prefix="InferenceWorker",
            )
            self._scheduler_thread = threading.Thread(
                target=self._run_scheduler_loop,
                name="VideoProcessorScheduler",
                daemon=True,
            )
            self._scheduler_thread.start()
            self.logger.info(
                "Video processor scheduler started. detect_interval_seconds=%s max_inference_workers=%s display_detection_overlay=%s",
                self.detect_interval_seconds,
                self.max_inference_workers,
                self.display_detection_overlay,
            )

    def stop_all(self) -> None:
        self._scheduler_stop_event.set()

        scheduler_thread = self._scheduler_thread
        if scheduler_thread and scheduler_thread.is_alive():
            scheduler_thread.join(timeout=5.0)
            if scheduler_thread.is_alive():
                self.logger.warning("Video processor scheduler did not exit within timeout.")

        executor = self._executor
        self._executor = None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=False)

        with self._lock:
            processors = list(self._processors.values())

        for processor in processors:
            processor.stop()

    def get_latest_frame(
        self,
        camera_id: str,
        display_detection_overlay: bool | None = None,
    ) -> np.ndarray | None:
        return self.get_latest_display_frame(
            camera_id,
            display_detection_overlay=display_detection_overlay,
        )

    def get_latest_display_frame(
        self,
        camera_id: str,
        display_detection_overlay: bool | None = None,
    ) -> np.ndarray | None:
        overlay_enabled = (
            self.display_detection_overlay
            if display_detection_overlay is None
            else bool(display_detection_overlay)
        )
        live_raw_frame = self.camera_manager.get_frame(camera_id)
        if live_raw_frame is not None:
            return self.render_display_frame(
                camera_id,
                live_raw_frame,
                display_detection_overlay=overlay_enabled,
            )

        with self._lock:
            processor = self._processors.get(camera_id)
        if processor is None:
            self.logger.warning("Processor not found when requesting display frame: %s", camera_id)
            return None
        return processor.get_latest_display_frame(overlay_enabled)

    def get_latest_snapshot_frame(self, camera_id: str) -> np.ndarray | None:
        with self._lock:
            processor = self._processors.get(camera_id)
        if processor is None:
            self.logger.warning("Processor not found when requesting snapshot frame: %s", camera_id)
            return None
        return processor.get_latest_snapshot_frame()

    def get_latest_raw_frame(self, camera_id: str) -> np.ndarray | None:
        with self._lock:
            processor = self._processors.get(camera_id)
        if processor is None:
            self.logger.warning("Processor not found when requesting raw frame: %s", camera_id)
            return None
        return processor.get_latest_raw_frame()

    def render_display_frame(
        self,
        camera_id: str,
        raw_frame: np.ndarray,
        display_detection_overlay: bool | None = None,
    ) -> np.ndarray:
        overlay_enabled = (
            self.display_detection_overlay
            if display_detection_overlay is None
            else bool(display_detection_overlay)
        )
        if raw_frame is None:
            return raw_frame

        if not overlay_enabled:
            return raw_frame.copy()

        detection_result = self.get_latest_detection(camera_id)
        if detection_result is None or not detection_result.detections:
            return raw_frame.copy()

        try:
            return self.detection_pipeline.annotate_frame(raw_frame, detection_result)
        except Exception as exc:
            self.logger.exception(
                "Failed to render overlay frame for camera %s: %s",
                camera_id,
                exc,
            )
            return raw_frame.copy()

    def get_latest_detection(self, camera_id: str) -> DetectionResult | None:
        with self._lock:
            processor = self._processors.get(camera_id)
        if processor is None:
            self.logger.warning(
                "Processor not found when requesting detection: %s", camera_id
            )
            return None
        return processor.get_latest_detection()

    def build_alarm_snapshot_frame(
        self,
        camera_id: str,
        events: list[ViolationEvent],
    ) -> np.ndarray | None:
        raw_frame = self.get_latest_raw_frame(camera_id)
        detection_result = self.get_latest_detection(camera_id)

        if raw_frame is None:
            return self.get_latest_snapshot_frame(camera_id)
        if detection_result is None:
            return raw_frame.copy()

        try:
            return self.detection_pipeline.annotate_frame(
                raw_frame,
                detection_result,
                violation_events=events,
            )
        except Exception as exc:
            self.logger.exception(
                "Failed to build alarm snapshot frame for camera %s: %s",
                camera_id,
                exc,
            )
            return raw_frame.copy()

    def has_camera(self, camera_id: str) -> bool:
        with self._lock:
            return camera_id in self._processors

    def add_camera(self, camera_id: str, enabled: bool) -> None:
        with self._lock:
            if camera_id in self._processors:
                raise ValueError(f"Processor already exists for camera {camera_id}")
            self._processors[camera_id] = StreamProcessor(
                camera_id=camera_id,
                camera_manager=self.camera_manager,
                detection_pipeline=self.detection_pipeline,
                rule_engine=self.rule_engine,
                alarm_manager=self.alarm_manager,
                detect_interval_seconds=self.detect_interval_seconds,
            )

        if enabled:
            self.logger.info("Camera %s added to scheduler.", camera_id)

    def remove_camera(self, camera_id: str) -> bool:
        with self._lock:
            processor = self._processors.pop(camera_id, None)

        if processor is None:
            return False

        processor.stop()
        return True

    def update_camera(
        self,
        camera_id: str,
        enabled: bool,
        previous_camera_id: str | None = None,
    ) -> None:
        target_camera_id = previous_camera_id or camera_id
        if previous_camera_id and previous_camera_id != camera_id and self.has_camera(camera_id):
            raise ValueError(f"Processor already exists for camera {camera_id}")

        self.remove_camera(target_camera_id)
        self.add_camera(camera_id, enabled)

    def replace_settings(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        detection_settings = settings.get("detection", {})
        self.detect_interval_seconds = self._get_detect_interval_seconds(detection_settings)
        self.max_inference_workers = max(
            1,
            int(detection_settings.get("max_inference_workers", 1)),
        )
        self.display_detection_overlay = self._get_display_detection_overlay(settings)
        self.load_from_settings()

    def _run_scheduler_loop(self) -> None:
        while not self._scheduler_stop_event.is_set():
            try:
                scheduled_any = False
                now = time.monotonic()
                enabled_camera_ids = self._get_enabled_camera_ids()

                with self._lock:
                    processors = {
                        camera_id: self._processors.get(camera_id)
                        for camera_id in enabled_camera_ids
                    }

                for camera_id in enabled_camera_ids:
                    processor = processors.get(camera_id)
                    if processor is None:
                        continue
                    if not processor.try_schedule(now):
                        continue
                    self._submit_processor(processor)
                    scheduled_any = True

                if not scheduled_any:
                    self._scheduler_stop_event.wait(0.05)
            except Exception as exc:
                self.logger.exception("Video processor scheduler loop failed: %s", exc)
                self._scheduler_stop_event.wait(0.2)

    def _submit_processor(self, processor: StreamProcessor) -> Future | None:
        executor = self._executor
        if executor is None:
            return None

        try:
            return executor.submit(processor.process_latest_frame)
        except Exception as exc:
            self.logger.exception(
                "Failed to submit inference task for camera %s: %s",
                processor.camera_id,
                exc,
            )
            processor.stop()
            return None

    def _get_enabled_camera_ids(self) -> list[str]:
        cameras = self.settings.get("cameras", [])
        return [
            str(camera["id"])
            for camera in cameras
            if bool(camera.get("enabled", False))
        ]

    def _get_detect_interval_seconds(self, detection_settings: dict[str, Any]) -> float:
        if "detect_interval_seconds" in detection_settings:
            return max(0.05, float(detection_settings["detect_interval_seconds"]))
        if "detect_interval" in detection_settings:
            return max(0.05, float(detection_settings["detect_interval"]))
        return 0.5

    def _get_display_detection_overlay(self, settings: dict[str, Any]) -> bool:
        display_settings = settings.get("display", {})
        return bool(display_settings.get("display_detection_overlay", False))
