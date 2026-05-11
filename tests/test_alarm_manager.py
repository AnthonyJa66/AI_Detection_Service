import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from app.models.violation_event import ViolationEvent
from app.services.alarm_manager import AlarmManager
from app.services.alarm_repository import SQLiteAlarmRepository


class FakeSnapshotProvider:
    def create_snapshot(self, events: list[ViolationEvent]) -> str | None:
        if not events:
            return None
        return f"snapshots/shared_{events[0].camera_id}_{events[0].timestamp}.jpg"


class RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[str] = []

    def notify(self, event: ViolationEvent) -> None:
        self.events.append(event.event_id)


class FailingNotifier:
    def notify(self, event: ViolationEvent) -> None:
        raise RuntimeError("notifier failed")


def make_event(camera_id: str = "cam_1", violation_type: str = "smoking") -> ViolationEvent:
    return ViolationEvent(
        event_id=str(uuid4()),
        camera_id=camera_id,
        violation_type=violation_type,
        timestamp="2026-04-20T10:00:00+00:00",
        confidence=0.95,
        snapshot_bbox=[1, 2, 3, 4],
        meta={"event_kind": "start"},
    )


class AlarmManagerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "alarm_test.db")
        self.repository = SQLiteAlarmRepository(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_repository_can_save_and_get_event(self) -> None:
        event = make_event()
        self.repository.save_event(event)

        stored = self.repository.get_event_by_id(event.event_id)

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.event_id, event.event_id)
        self.assertEqual(stored.camera_id, event.camera_id)
        self.assertEqual(stored.violation_type, event.violation_type)

    def test_repository_can_list_events_with_filters(self) -> None:
        event_1 = make_event(camera_id="cam_1", violation_type="smoking")
        event_2 = make_event(camera_id="cam_1", violation_type="no_helmet")
        event_3 = make_event(camera_id="cam_2", violation_type="smoking")

        self.repository.save_event(event_1)
        self.repository.save_event(event_2)
        self.repository.save_event(event_3)

        filtered = self.repository.list_events(camera_id="cam_1", violation_type="smoking")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].event_id, event_1.event_id)

    def test_alarm_manager_ignores_empty_event_list(self) -> None:
        manager = AlarmManager(repository=self.repository)
        result = manager.handle_events([])
        self.assertEqual(result, [])

    def test_alarm_manager_enriches_snapshot_and_saves(self) -> None:
        notifier = RecordingNotifier()
        manager = AlarmManager(
            repository=self.repository,
            snapshot_provider=FakeSnapshotProvider(),
            notifier=notifier,
            async_mode=False,
        )
        event = make_event()

        saved_events = manager.handle_events([event])

        self.assertEqual(len(saved_events), 1)
        expected_path = f"snapshots/shared_{event.camera_id}_{event.timestamp}.jpg"
        self.assertEqual(saved_events[0].snapshot_path, expected_path)
        self.assertEqual(notifier.events, [event.event_id])

        stored = self.repository.get_event_by_id(event.event_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.snapshot_path, expected_path)

    def test_grouped_events_share_one_snapshot_path(self) -> None:
        manager = AlarmManager(
            repository=self.repository,
            snapshot_provider=FakeSnapshotProvider(),
            notifier=RecordingNotifier(),
            async_mode=False,
        )
        event_1 = make_event(violation_type="no_helmet")
        event_2 = ViolationEvent(
            event_id=str(uuid4()),
            camera_id=event_1.camera_id,
            violation_type="no_vest",
            timestamp=event_1.timestamp,
            confidence=0.98,
            snapshot_bbox=[5, 6, 7, 8],
            meta={"confirm_counts": 2},
        )

        saved_events = manager.handle_events([event_1, event_2])

        self.assertEqual(len(saved_events), 2)
        self.assertEqual(saved_events[0].snapshot_path, saved_events[1].snapshot_path)

    def test_notifier_failure_does_not_break_flow(self) -> None:
        manager = AlarmManager(
            repository=self.repository,
            snapshot_provider=FakeSnapshotProvider(),
            notifier=FailingNotifier(),
            async_mode=False,
        )
        event = make_event()

        saved_events = manager.handle_events([event])

        self.assertEqual(len(saved_events), 1)
        stored = self.repository.get_event_by_id(event.event_id)
        self.assertIsNotNone(stored)


if __name__ == "__main__":
    unittest.main()
