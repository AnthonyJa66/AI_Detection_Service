import unittest

import numpy as np

from app.models import DetectionItem, DetectionResult
from app.services.video_processor import StreamProcessor, VideoProcessor


class FakeCameraManager:
    def __init__(self) -> None:
        self.frame = np.zeros((16, 16, 3), dtype=np.uint8)

    def get_frame(self, camera_id: str, copy: bool = True):
        if copy:
            return self.frame.copy()
        return self.frame


class FakeDetectionPipeline:
    def detect(self, camera_id: str, frame: np.ndarray) -> DetectionResult:
        return DetectionResult(
            camera_id=camera_id,
            timestamp="2026-04-22T10:00:00+00:00",
            frame_width=frame.shape[1],
            frame_height=frame.shape[0],
            detections=[
                DetectionItem(
                    class_name="smoking",
                    confidence=0.9,
                    bbox=[1, 1, 8, 8],
                    source_model="test",
                )
            ],
        )

    def annotate_frame(self, frame: np.ndarray, detection_result: DetectionResult) -> np.ndarray:
        annotated = frame.copy()
        annotated[0, 0] = [255, 255, 255]
        return annotated


class StreamProcessorTestCase(unittest.TestCase):
    def test_display_and_snapshot_frames_are_split(self) -> None:
        processor = StreamProcessor(
            camera_id="cam_1",
            camera_manager=FakeCameraManager(),
            detection_pipeline=FakeDetectionPipeline(),
            rule_engine=None,
            alarm_manager=None,
            detect_interval_seconds=0.5,
        )

        processor.process_latest_frame()

        display_frame = processor.get_latest_display_frame(display_detection_overlay=False)
        snapshot_frame = processor.get_latest_snapshot_frame()

        self.assertIsNotNone(display_frame)
        self.assertIsNotNone(snapshot_frame)
        assert display_frame is not None
        assert snapshot_frame is not None
        self.assertEqual(display_frame[0, 0].tolist(), [0, 0, 0])
        self.assertEqual(snapshot_frame[0, 0].tolist(), [255, 255, 255])

    def test_display_can_still_use_overlay_when_enabled(self) -> None:
        processor = StreamProcessor(
            camera_id="cam_1",
            camera_manager=FakeCameraManager(),
            detection_pipeline=FakeDetectionPipeline(),
            rule_engine=None,
            alarm_manager=None,
            detect_interval_seconds=0.5,
        )

        processor.process_latest_frame()

        overlay_frame = processor.get_latest_display_frame(display_detection_overlay=True)

        self.assertIsNotNone(overlay_frame)
        assert overlay_frame is not None
        self.assertEqual(overlay_frame[0, 0].tolist(), [255, 255, 255])

    def test_video_processor_renders_overlay_on_live_raw_frame(self) -> None:
        camera_manager = FakeCameraManager()
        camera_manager.frame[0, 0] = [10, 20, 30]
        settings = {
            "project_root": "",
            "detection": {
                "confidence": 0.5,
                "safety_confidence": 0.5,
                "smoking_confidence": 0.7,
                "detect_interval_seconds": 0.5,
                "max_inference_workers": 1,
            },
            "display": {
                "display_detection_overlay": False,
            },
            "cameras": [
                {
                    "id": "cam_1",
                    "enabled": True,
                }
            ],
        }
        video_processor = VideoProcessor(
            camera_manager=camera_manager,
            settings=settings,
            detection_pipeline=FakeDetectionPipeline(),
            rule_engine=None,
            alarm_manager=None,
        )
        video_processor.load_from_settings()
        stream_processor = video_processor._processors["cam_1"]
        stream_processor.process_latest_frame()

        raw_frame = video_processor.get_latest_display_frame(
            "cam_1",
            display_detection_overlay=False,
        )
        overlay_frame = video_processor.get_latest_display_frame(
            "cam_1",
            display_detection_overlay=True,
        )

        self.assertIsNotNone(raw_frame)
        self.assertIsNotNone(overlay_frame)
        assert raw_frame is not None
        assert overlay_frame is not None
        self.assertEqual(raw_frame[0, 0].tolist(), [10, 20, 30])
        self.assertEqual(overlay_frame[0, 0].tolist(), [255, 255, 255])


if __name__ == "__main__":
    unittest.main()
