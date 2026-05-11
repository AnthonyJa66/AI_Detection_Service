"""报警事件管理。

负责把规则事件落库、补截图，并通过通知器分发到 WebSocket 等下游。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import queue
import threading
import time
from typing import Protocol
from uuid import uuid4

from app.logger import get_logger
from app.models.violation_event import ViolationEvent
from app.services.alarm_repository import AlarmRepository


class SnapshotProvider(Protocol):
    def create_snapshot(self, events: list[ViolationEvent]) -> str | None:
        ...


class AlarmNotifier(Protocol):
    def notify(self, event: ViolationEvent) -> None:
        ...


class NullAlarmNotifier:
    def notify(self, event: ViolationEvent) -> None:
        return None


class AlarmManager:
    """统一管理报警事件的持久化与异步处理。"""

    def __init__(
        self,
        repository: AlarmRepository,
        snapshot_provider: SnapshotProvider | None = None,
        notifier: AlarmNotifier | None = None,
        async_mode: bool = False,
    ) -> None:
        self.logger = get_logger("video_monitor.alarm_manager")
        self.snapshot_provider = snapshot_provider
        self.notifier = notifier or NullAlarmNotifier()
        self.repository = repository
        self.async_mode = bool(async_mode)
        self._queue: queue.Queue[list[ViolationEvent] | None] = queue.Queue()
        self._worker_stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._worker_lock = threading.Lock()

    def create_alarm(self, event: dict[str, object]) -> list[ViolationEvent]:
        """接收规则事件并转换为持久化对象。"""
        if not event:
            return []

        violation_event = self._event_dict_to_violation_event(event)

        if not self.async_mode:
            return self._persist_events([violation_event])

        if self._worker_thread is None or not self._worker_thread.is_alive():
            self.start()

        self._queue.put([violation_event])
        return [violation_event]

    def start(self) -> None:
        if not self.async_mode:
            return

        with self._worker_lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return

            self._worker_stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._run_worker_loop,
                name="AlarmManagerWorker",
                daemon=True,
            )
            self._worker_thread.start()
            self.logger.info("Alarm worker started.")

    def stop(self, timeout: float = 5.0) -> None:
        if not self.async_mode:
            return

        self._worker_stop_event.set()
        self._queue.put(None)

        worker_thread = self._worker_thread
        if worker_thread and worker_thread.is_alive():
            worker_thread.join(timeout=timeout)
            if worker_thread.is_alive():
                self.logger.warning("Alarm worker did not exit within timeout.")

    def handle_events(self, events: list[ViolationEvent]) -> list[ViolationEvent]:
        if not events:
            return []

        events = self._merge_events(events)

        if not self.async_mode:
            return self._persist_events(events)

        if self._worker_thread is None or not self._worker_thread.is_alive():
            self.start()

        self._queue.put(list(events))
        return list(events)

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        if not self.async_mode:
            return True

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.02)
        return self._queue.unfinished_tasks == 0

    def _run_worker_loop(self) -> None:
        while True:
            try:
                event_batch = self._queue.get(timeout=0.2)
            except queue.Empty:
                if self._worker_stop_event.is_set():
                    break
                continue

            try:
                if event_batch is None:
                    if self._worker_stop_event.is_set():
                        break
                    continue
                self._persist_events(event_batch)
            except Exception as exc:
                self.logger.exception("Alarm worker failed: %s", exc)
            finally:
                self._queue.task_done()

    def _persist_events(self, events: list[ViolationEvent]) -> list[ViolationEvent]:
        normalized_events = self._normalize_events(events)
        persisted_events: list[ViolationEvent] = []
        for event in normalized_events:
            try:
                self.repository.save_event(event)
                self._notify(event)
                persisted_events.append(event)
            except Exception as exc:
                self.logger.exception(
                    "Failed to handle event %s: %s",
                    getattr(event, "event_id", "unknown"),
                    exc,
                )
        return persisted_events

    def _merge_events(self, events: list[ViolationEvent]) -> list[ViolationEvent]:
        """把同一时刻的多类违规合并成一条综合报警。"""
        if not events:
            return []
        if len(events) == 1:
            return list(events)

        first_event = events[0]
        merged_violation_types: list[str] = []
        merged_violation_counts: dict[str, int] = {}
        merged_confidence = 0.0
        merged_bbox = first_event.snapshot_bbox

        for event in events:
            meta_types = event.meta.get("violation_types") or [event.violation_type]
            for violation_type in meta_types:
                if violation_type not in merged_violation_types:
                    merged_violation_types.append(violation_type)
            for violation_type, count in dict(event.meta.get("violation_counts") or {}).items():
                merged_violation_counts[violation_type] = int(count)
            merged_confidence = max(merged_confidence, float(event.confidence))
            if merged_bbox is None and event.snapshot_bbox is not None:
                merged_bbox = event.snapshot_bbox

        alarm_type = str(
            first_event.meta.get("alarm_type")
            or " / ".join(merged_violation_types)
        )
        merged_event = replace(
            first_event,
            confidence=merged_confidence,
            snapshot_bbox=merged_bbox,
            meta={
                **first_event.meta,
                "alarm_type": alarm_type,
                "violation_types": merged_violation_types,
                "violation_counts": merged_violation_counts,
                "violation_count": int(sum(merged_violation_counts.values())),
            },
        )
        return [merged_event]

    def _normalize_events(self, events: list[ViolationEvent]) -> list[ViolationEvent]:
        """为事件批次补齐截图路径。"""
        if self.snapshot_provider is None:
            return list(events)

        snapshot_cache: dict[tuple[str, str], str | None] = {}
        grouped_events: dict[tuple[str, str], list[ViolationEvent]] = {}

        for event in events:
            if event.snapshot_path is not None:
                continue
            group_key = (event.camera_id, event.timestamp)
            grouped_events.setdefault(group_key, []).append(event)

        for group_key, event_group in grouped_events.items():
            try:
                snapshot_cache[group_key] = self.snapshot_provider.create_snapshot(event_group)
            except Exception as exc:
                self.logger.exception(
                    "Snapshot provider failed for events %s: %s",
                    [event.event_id for event in event_group],
                    exc,
                )
                snapshot_cache[group_key] = None

        normalized_events: list[ViolationEvent] = []
        for event in events:
            if event.snapshot_path is not None:
                normalized_events.append(event)
                continue

            group_key = (event.camera_id, event.timestamp)
            normalized_events.append(
                replace(event, snapshot_path=snapshot_cache.get(group_key))
            )

        return normalized_events

    def _notify(self, event: ViolationEvent) -> None:
        try:
            self.notifier.notify(event)
        except Exception as exc:
            self.logger.exception(
                "Notifier failed for event %s: %s",
                event.event_id,
                exc,
            )

    def _event_dict_to_violation_event(self, event: dict[str, object]) -> ViolationEvent:
        state = tuple(event.get("state") or (0, 0, 0))
        counts = {
            "no_helmet": int(state[0] if len(state) > 0 else 0),
            "no_vest": int(state[1] if len(state) > 1 else 0),
            "smoking": int(state[2] if len(state) > 2 else 0),
        }
        alarm_type = str(event.get("alarm_type") or "")
        timestamp = self._timestamp_to_iso(event.get("timestamp"))
        return ViolationEvent(
            event_id=str(uuid4()),
            camera_id=str(event.get("camera_id") or ""),
            violation_type=alarm_type,
            timestamp=timestamp,
            confidence=1.0,
            meta={
                "event_kind": "state_change",
                "alarm_type": alarm_type,
                "violation_counts": counts,
                "violation_count": int(sum(counts.values())),
                "state": state,
            },
        )

    def _timestamp_to_iso(self, value: object) -> str:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        if isinstance(value, str) and value:
            return value
        return datetime.now(timezone.utc).isoformat()
