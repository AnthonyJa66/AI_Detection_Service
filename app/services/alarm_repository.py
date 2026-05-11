from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.logger import get_logger
from app.models.violation_event import ViolationEvent


CREATE_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS violation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    camera_id TEXT NOT NULL,
    violation_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    confidence REAL NOT NULL,
    snapshot_path TEXT,
    meta_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


INSERT_EVENT_SQL = """
INSERT INTO violation_events (
    event_id,
    camera_id,
    violation_type,
    timestamp,
    confidence,
    snapshot_path,
    meta_json,
    created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
"""


SELECT_EVENT_BASE_SQL = """
SELECT
    id,
    event_id,
    camera_id,
    violation_type,
    timestamp,
    confidence,
    snapshot_path,
    meta_json,
    created_at
FROM violation_events
"""


class AlarmRepository(ABC):
    @abstractmethod
    def save_event(self, event: ViolationEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_events(
        self,
        camera_id: str | None = None,
        violation_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ViolationEvent]:
        raise NotImplementedError

    @abstractmethod
    def get_event_by_id(self, event_id: str) -> ViolationEvent | None:
        raise NotImplementedError

    @abstractmethod
    def count_events(
        self,
        camera_id: str | None = None,
        violation_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    def get_statistics(
        self,
        camera_id: str | None = None,
        violation_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class SQLiteAlarmRepository(AlarmRepository):
    def __init__(self, db_path: str) -> None:
        self.logger = get_logger("video_monitor.alarm_repository")
        self.db_path = str(Path(db_path))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def save_event(self, event: ViolationEvent) -> None:
        meta_payload = dict(event.meta)
        meta_payload["snapshot_bbox"] = event.snapshot_bbox
        meta_json = json.dumps(meta_payload, ensure_ascii=True, sort_keys=True)
        created_at = datetime.now(timezone.utc).isoformat()

        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    INSERT_EVENT_SQL,
                    (
                        event.event_id,
                        event.camera_id,
                        event.violation_type,
                        event.timestamp,
                        float(event.confidence),
                        event.snapshot_path,
                        meta_json,
                        created_at,
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            self.logger.exception("Failed to save event %s: %s", event.event_id, exc)
            raise

    def list_events(
        self,
        camera_id: str | None = None,
        violation_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ViolationEvent]:
        clauses, params = self._build_filter_clauses(
            camera_id=camera_id,
            violation_type=violation_type,
            start_time=start_time,
            end_time=end_time,
        )

        query = SELECT_EVENT_BASE_SQL
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([max(1, int(limit)), max(0, int(offset))])

        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(query, params).fetchall()
        except sqlite3.Error as exc:
            self.logger.exception("Failed to list events: %s", exc)
            raise

        return [self._row_to_event(row) for row in rows]

    def get_event_by_id(self, event_id: str) -> ViolationEvent | None:
        query = SELECT_EVENT_BASE_SQL + " WHERE event_id = ? LIMIT 1"
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(query, (event_id,)).fetchone()
        except sqlite3.Error as exc:
            self.logger.exception("Failed to fetch event %s: %s", event_id, exc)
            raise

        if row is None:
            return None
        return self._row_to_event(row)

    def count_events(
        self,
        camera_id: str | None = None,
        violation_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> int:
        clauses, params = self._build_filter_clauses(
            camera_id=camera_id,
            violation_type=violation_type,
            start_time=start_time,
            end_time=end_time,
        )

        query = "SELECT COUNT(*) AS total FROM violation_events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)

        try:
            with closing(self._connect()) as connection:
                row = connection.execute(query, params).fetchone()
        except sqlite3.Error as exc:
            self.logger.exception("Failed to count events: %s", exc)
            raise

        return int(row["total"]) if row is not None else 0

    def get_statistics(
        self,
        camera_id: str | None = None,
        violation_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict[str, Any]:
        clauses, params = self._build_filter_clauses(
            camera_id=camera_id,
            violation_type=violation_type,
            start_time=start_time,
            end_time=end_time,
        )

        where_clause = ""
        if clauses:
            where_clause = " WHERE " + " AND ".join(clauses)

        total_query = "SELECT COUNT(*) AS total FROM violation_events" + where_clause
        violation_query = (
            "SELECT violation_type, COUNT(*) AS total "
            "FROM violation_events"
            + where_clause
            + " GROUP BY violation_type ORDER BY total DESC, violation_type ASC"
        )
        camera_query = (
            "SELECT camera_id, COUNT(*) AS total "
            "FROM violation_events"
            + where_clause
            + " GROUP BY camera_id ORDER BY total DESC, camera_id ASC"
        )

        try:
            with closing(self._connect()) as connection:
                total_row = connection.execute(total_query, params).fetchone()
                violation_rows = connection.execute(violation_query, params).fetchall()
                camera_rows = connection.execute(camera_query, params).fetchall()
        except sqlite3.Error as exc:
            self.logger.exception("Failed to gather statistics: %s", exc)
            raise

        return {
            "total_events": int(total_row["total"]) if total_row is not None else 0,
            "by_violation_type": [
                {
                    "violation_type": row["violation_type"],
                    "count": int(row["total"]),
                }
                for row in violation_rows
            ],
            "by_camera": [
                {
                    "camera_id": row["camera_id"],
                    "count": int(row["total"]),
                }
                for row in camera_rows
            ],
        }

    def _initialize_database(self) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute(CREATE_EVENTS_TABLE_SQL)
                connection.commit()
        except sqlite3.Error as exc:
            self.logger.exception("Failed to initialize alarm database: %s", exc)
            raise

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _row_to_event(self, row: sqlite3.Row) -> ViolationEvent:
        try:
            meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
        except json.JSONDecodeError:
            self.logger.warning("Failed to decode meta_json for event %s", row["event_id"])
            meta = {}

        meta = dict(meta)
        snapshot_bbox = meta.pop("snapshot_bbox", None)
        meta["db_id"] = row["id"]
        meta["created_at"] = row["created_at"]

        return ViolationEvent(
            event_id=row["event_id"],
            camera_id=row["camera_id"],
            violation_type=row["violation_type"],
            timestamp=row["timestamp"],
            confidence=float(row["confidence"]),
            snapshot_path=row["snapshot_path"],
            snapshot_bbox=snapshot_bbox,
            meta=meta,
        )

    def _build_filter_clauses(
        self,
        camera_id: str | None = None,
        violation_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)

        if violation_type:
            clauses.append("violation_type = ?")
            params.append(violation_type)

        if start_time:
            clauses.append("timestamp >= ?")
            params.append(start_time)

        if end_time:
            clauses.append("timestamp <= ?")
            params.append(end_time)

        return clauses, params
