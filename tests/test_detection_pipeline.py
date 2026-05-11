import unittest

import numpy as np

from app.services.detection_pipeline import DetectionPipeline


class FakeModelManager:
    def predict_all(self, frame: np.ndarray) -> dict:
        return {
            "ultra": [
                {
                    "raw_class_name": "hardhat",
                    "confidence": 0.91,
                    "bbox": [10, 20, 100, 120],
                    "source_model": "ultra",
                },
                {
                    "raw_class_name": "person",
                    "confidence": 0.88,
                    "bbox": [15, 30, 140, 220],
                    "source_model": "ultra",
                },
            ],
            "smoking": [
                {
                    "raw_class_name": "smoking",
                    "confidence": 0.77,
                    "bbox": [50, 60, 160, 200],
                    "source_model": "smoking",
                }
            ],
        }


class FailingModelManager:
    def predict_all(self, frame: np.ndarray) -> dict:
        raise RuntimeError("inference failed")


class DetectionPipelineTestCase(unittest.TestCase):
    def test_detect_merges_and_normalizes_classes(self) -> None:
        pipeline = DetectionPipeline(model_manager=FakeModelManager())
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        result = pipeline.detect("cam_1", frame)

        self.assertEqual(result.camera_id, "cam_1")
        self.assertEqual(result.frame_width, 320)
        self.assertEqual(result.frame_height, 240)
        self.assertEqual(len(result.detections), 3)
        self.assertEqual(result.detections[0].class_name, "helmet")
        self.assertEqual(result.detections[2].class_name, "smoking")

    def test_detect_returns_empty_result_on_failure(self) -> None:
        pipeline = DetectionPipeline(model_manager=FailingModelManager())
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        result = pipeline.detect("cam_2", frame)

        self.assertEqual(result.camera_id, "cam_2")
        self.assertEqual(result.frame_width, 160)
        self.assertEqual(result.frame_height, 120)
        self.assertEqual(result.detections, [])

    def test_annotate_frame_preserves_shape(self) -> None:
        pipeline = DetectionPipeline(model_manager=FakeModelManager())
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        result = pipeline.detect("cam_3", frame)

        annotated = pipeline.annotate_frame(frame, result)

        self.assertEqual(annotated.shape, frame.shape)
        self.assertFalse(np.shares_memory(annotated, frame))

    def test_invalid_frame_returns_empty_result(self) -> None:
        pipeline = DetectionPipeline(model_manager=FakeModelManager())

        result = pipeline.detect("cam_4", np.array([]))

        self.assertEqual(result.detections, [])
        self.assertEqual(result.frame_width, 0)
        self.assertEqual(result.frame_height, 0)


if __name__ == "__main__":
    unittest.main()
