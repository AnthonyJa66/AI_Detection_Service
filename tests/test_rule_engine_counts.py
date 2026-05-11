import unittest

from app.models import DetectionItem, DetectionResult
from app.services.rule_engine import RuleEngine
from app.utils import summarize_violation_counts


class RuleEngineCountsTestCase(unittest.TestCase):
    def test_violation_count_change_triggers_update_event(self) -> None:
        engine = RuleEngine(
            confirm_counts={"no_helmet": 1, "no_vest": 1, "smoking": 1},
            clear_count=2,
            enable_reminder_events=False,
        )

        first = DetectionResult(
            camera_id="cam_1",
            timestamp="2026-04-22T10:00:00+00:00",
            frame_width=1280,
            frame_height=720,
            detections=[
                DetectionItem("no_helmet", 0.8, [0, 0, 10, 10], "ultra"),
            ],
        )
        second = DetectionResult(
            camera_id="cam_1",
            timestamp="2026-04-22T10:00:01+00:00",
            frame_width=1280,
            frame_height=720,
            detections=[
                DetectionItem("no_helmet", 0.8, [0, 0, 10, 10], "ultra"),
                DetectionItem("no_helmet", 0.85, [20, 20, 30, 30], "ultra"),
            ],
        )

        first_events = engine.process(first)
        second_events = engine.process(second)

        self.assertEqual(len(first_events), 1)
        self.assertEqual(first_events[0].meta["event_kind"], "start")
        self.assertEqual(first_events[0].meta["violation_count"], 1)
        self.assertEqual(len(second_events), 1)
        self.assertEqual(second_events[0].meta["event_kind"], "update")
        self.assertEqual(second_events[0].meta["violation_count"], 2)

    def test_detection_summary_reports_current_violation_counts(self) -> None:
        detection_result = DetectionResult(
            camera_id="cam_1",
            timestamp="2026-04-22T10:00:00+00:00",
            frame_width=1280,
            frame_height=720,
            detections=[
                DetectionItem("no_helmet", 0.8, [0, 0, 10, 10], "ultra"),
                DetectionItem("no_vest", 0.82, [20, 20, 40, 40], "ultra"),
                DetectionItem("smoking", 0.55, [50, 50, 60, 60], "smoking"),
                DetectionItem("smoking", 0.58, [70, 70, 80, 80], "smoking"),
            ],
        )

        summary = summarize_violation_counts(detection_result)

        self.assertEqual(summary["no_helmet_count"], 1)
        self.assertEqual(summary["no_vest_count"], 1)
        self.assertEqual(summary["smoking_count"], 2)


if __name__ == "__main__":
    unittest.main()
