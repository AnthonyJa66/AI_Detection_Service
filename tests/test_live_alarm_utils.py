import unittest

from app.models.violation_event import ViolationEvent
from app.utils import aggregate_live_alarm_events


class LiveAlarmUtilsTestCase(unittest.TestCase):
    def test_events_with_same_snapshot_are_aggregated_for_live_view(self) -> None:
        first = ViolationEvent(
            event_id="event-1",
            camera_id="cam_1",
            violation_type="no_helmet",
            timestamp="2026-04-22T10:00:00+00:00",
            confidence=1.0,
            snapshot_path="2026-04-22/cam_1/a.jpg",
            meta={
                "event_kind": "start",
                "session_started_at": "2026-04-22T10:00:00+00:00",
            },
        )
        second = ViolationEvent(
            event_id="event-2",
            camera_id="cam_1",
            violation_type="no_vest",
            timestamp="2026-04-22T10:00:00+00:00",
            confidence=1.0,
            snapshot_path="2026-04-22/cam_1/a.jpg",
            meta={
                "event_kind": "start",
                "session_started_at": "2026-04-22T10:00:00+00:00",
            },
        )

        items = aggregate_live_alarm_events(
            [first, second],
            camera_name_map={"cam_1": "工地入口"},
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["camera_name"], "工地入口")
        self.assertEqual(items[0]["violation_types"], ["no_helmet", "no_vest"])
        self.assertEqual(items[0]["violation_type_text"], "无安全帽 / 无反光背心")
        self.assertEqual(items[0]["snapshot_path"], "2026-04-22/cam_1/a.jpg")
        self.assertEqual(items[0]["raw_event_ids"], ["event-1", "event-2"])


if __name__ == "__main__":
    unittest.main()
