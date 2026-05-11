import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from app.models.violation_event import ViolationEvent
from app.services.alarm_repository import SQLiteAlarmRepository


def make_event(
    event_id: str | None = None,
    camera_id: str = "cam_1",
    violation_type: str = "smoking",
    timestamp: str = "2026-04-20T10:00:00+00:00",
) -> ViolationEvent:
    return ViolationEvent(
        event_id=event_id or str(uuid4()),
        camera_id=camera_id,
        violation_type=violation_type,
        timestamp=timestamp,
        confidence=0.9,
        snapshot_path=None,
        snapshot_bbox=[1, 2, 3, 4],
        meta={"source": "test"},
    )


class SQLiteAlarmRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "events.db")
        self.repository = SQLiteAlarmRepository(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_and_get_event(self) -> None:
        event = make_event()

        self.repository.save_event(event)
        stored = self.repository.get_event_by_id(event.event_id)

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.event_id, event.event_id)
        self.assertEqual(stored.camera_id, "cam_1")
        self.assertEqual(stored.violation_type, "smoking")

    def test_list_count_and_statistics_with_filters(self) -> None:
        events = [
            make_event(camera_id="cam_1", violation_type="smoking", timestamp="2026-04-20T10:00:00+00:00"),
            make_event(camera_id="cam_1", violation_type="no_helmet", timestamp="2026-04-20T11:00:00+00:00"),
            make_event(camera_id="cam_2", violation_type="smoking", timestamp="2026-04-20T12:00:00+00:00"),
        ]
        for event in events:
            self.repository.save_event(event)

        filtered_events = self.repository.list_events(camera_id="cam_1")
        filtered_count = self.repository.count_events(violation_type="smoking")
        filtered_stats = self.repository.get_statistics(
            start_time="2026-04-20T09:30:00+00:00",
            end_time="2026-04-20T11:30:00+00:00",
        )

        self.assertEqual(len(filtered_events), 2)
        self.assertEqual(filtered_count, 2)
        self.assertEqual(filtered_stats["total_events"], 2)
        self.assertEqual(filtered_stats["by_violation_type"][0]["count"], 1)
        self.assertEqual(len(filtered_stats["by_camera"]), 1)

    def test_list_events_respects_offset_and_limit(self) -> None:
        event_ids = []
        for index in range(5):
            event = make_event(timestamp=f"2026-04-20T10:00:0{index}+00:00")
            event_ids.append(event.event_id)
            self.repository.save_event(event)

        results = self.repository.list_events(limit=2, offset=1)

        self.assertEqual(len(results), 2)
        self.assertNotEqual(results[0].event_id, event_ids[-1])


if __name__ == "__main__":
    unittest.main()
