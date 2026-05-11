import unittest

from app.models import DetectionItem, DetectionResult
from app.services.rule_engine import RuleEngine


def make_result(camera_id: str, timestamp: float, detections: list[DetectionItem]) -> DetectionResult:
    return DetectionResult(
        camera_id=camera_id,
        timestamp=timestamp,
        frame_width=1280,
        frame_height=720,
        detections=detections,
    )


def make_detection(
    class_name: str,
    confidence: float = 0.9,
    bbox: list[int] | None = None,
) -> DetectionItem:
    return DetectionItem(
        class_name=class_name,
        confidence=confidence,
        bbox=bbox or [10, 10, 100, 100],
        source_model="test",
    )


class RuleEngineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RuleEngine(
            confirm_counts={
                "no_helmet": 2,
                "no_vest": 2,
                "smoking": 3,
            },
            clear_count=4,
            session_end_grace_seconds=2.0,
            enable_reminder_events=False,
            reminder_interval_seconds=60,
        )

    def test_smoking_starts_on_third_consecutive_hit(self) -> None:
        frame_1 = make_result("cam_1", 1.0, [make_detection("smoking", 0.8)])
        frame_2 = make_result("cam_1", 2.0, [make_detection("smoking", 0.85)])
        frame_3 = make_result("cam_1", 3.0, [make_detection("smoking", 0.9)])

        self.assertEqual(self.engine.process(frame_1), [])
        self.assertEqual(self.engine.process(frame_2), [])
        events = self.engine.process(frame_3)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].violation_type, "smoking")
        self.assertEqual(events[0].meta["event_kind"], "start")

    def test_active_session_does_not_repeat_start_alarm(self) -> None:
        detections = [make_detection("person", 0.99)]

        self.assertEqual(self.engine.process(make_result("cam_1", 1.0, detections)), [])
        first_events = self.engine.process(make_result("cam_1", 2.0, detections))
        second_events = self.engine.process(make_result("cam_1", 3.0, detections))
        third_events = self.engine.process(make_result("cam_1", 4.0, detections))

        self.assertEqual(len(first_events), 2)
        self.assertEqual(second_events, [])
        self.assertEqual(third_events, [])

    def test_short_miss_does_not_end_active_session(self) -> None:
        detections = [make_detection("person", 0.99)]
        self.engine.process(make_result("cam_1", 1.0, detections))
        self.engine.process(make_result("cam_1", 2.0, detections))

        self.assertEqual(self.engine.process(make_result("cam_1", 3.0, [])), [])
        restart_events = self.engine.process(make_result("cam_1", 4.0, detections))

        self.assertEqual(restart_events, [])

    def test_session_ends_after_clear_threshold(self) -> None:
        detections = [make_detection("person", 0.99)]
        self.engine.process(make_result("cam_1", 1.0, detections))
        self.engine.process(make_result("cam_1", 2.0, detections))

        self.engine.process(make_result("cam_1", 5.0, []))
        self.engine.process(make_result("cam_1", 6.0, []))
        self.engine.process(make_result("cam_1", 7.0, []))
        self.engine.process(make_result("cam_1", 8.0, []))

        self.assertEqual(self.engine.process(make_result("cam_1", 9.0, detections)), [])
        restart_events = self.engine.process(make_result("cam_1", 10.0, detections))

        violation_types = {event.violation_type for event in restart_events}
        self.assertIn("no_helmet", violation_types)
        self.assertIn("no_vest", violation_types)

    def test_camera_states_are_isolated(self) -> None:
        self.engine.process(make_result("cam_1", 1.0, [make_detection("smoking")]))
        self.engine.process(make_result("cam_1", 2.0, [make_detection("smoking")]))

        cam_2_events = self.engine.process(
            make_result("cam_2", 3.0, [make_detection("smoking")])
        )

        self.assertEqual(cam_2_events, [])

        cam_1_events = self.engine.process(
            make_result("cam_1", 3.0, [make_detection("smoking")])
        )
        self.assertEqual(len(cam_1_events), 1)


if __name__ == "__main__":
    unittest.main()
