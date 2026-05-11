from __future__ import annotations

import json
import threading
from typing import Any
from urllib.parse import quote

from app.logger import get_logger
from app.models.violation_event import ViolationEvent
from app.utils import (
    build_live_alarm_group_key,
    format_display_time,
    get_display_label,
    normalize_label_name,
)


class WebSocketConnectionManager:
    def __init__(self) -> None:
        self.logger = get_logger("video_monitor.websocket")
        self._clients: set[Any] = set()
        self._lock = threading.Lock()

    def handle_client(self, ws: Any) -> None:
        self._register(ws)
        try:
            while True:
                message = ws.receive()
                if message is None:
                    break
        except Exception as exc:
            self.logger.warning("WebSocket client disconnected with error: %s", exc)
        finally:
            self._unregister(ws)

    def broadcast_alarm(self, event: ViolationEvent) -> None:
        aggregate_key = build_live_alarm_group_key(event)
        normalized_type = normalize_label_name(event.violation_type)
        payload = {
            "type": "alarm_event",
            "data": {
                "event_id": aggregate_key,
                "aggregate_key": aggregate_key,
                "camera_id": event.camera_id,
                "raw_event_ids": [event.event_id],
                "violation_type": normalized_type,
                "violation_types": [normalized_type],
                "violation_counts": {
                    normalized_type: int(event.meta.get("violation_count") or 0),
                },
                "violation_type_text": get_display_label(normalized_type),
                "timestamp": event.timestamp,
                "display_time": format_display_time(event.timestamp),
                "confidence": event.confidence,
                "snapshot_path": event.snapshot_path,
                "snapshot_url": _build_snapshot_url(event.snapshot_path),
            },
        }
        self.broadcast_json(payload)

    def broadcast_json(self, payload: dict[str, Any]) -> None:
        message = json.dumps(payload, ensure_ascii=True)
        with self._lock:
            clients = list(self._clients)

        stale_clients: list[Any] = []
        for client in clients:
            try:
                client.send(message)
            except Exception as exc:
                self.logger.warning("Failed to send WebSocket message: %s", exc)
                stale_clients.append(client)

        for client in stale_clients:
            self._unregister(client)

    def _register(self, ws: Any) -> None:
        with self._lock:
            self._clients.add(ws)
            client_count = len(self._clients)
        self.logger.info("WebSocket client connected. Total clients: %s", client_count)

    def _unregister(self, ws: Any) -> None:
        with self._lock:
            self._clients.discard(ws)
            client_count = len(self._clients)
        self.logger.info("WebSocket client disconnected. Total clients: %s", client_count)


class WebSocketAlarmNotifier:
    def __init__(self, connection_manager: WebSocketConnectionManager) -> None:
        self.connection_manager = connection_manager
        self.logger = get_logger("video_monitor.websocket_notifier")

    def notify(self, event: ViolationEvent) -> None:
        try:
            self.connection_manager.broadcast_alarm(event)
        except Exception as exc:
            self.logger.exception(
                "WebSocket broadcast failed for event %s: %s",
                event.event_id,
                exc,
            )


def _build_snapshot_url(snapshot_path: str | None) -> str | None:
    if not snapshot_path:
        return None

    normalized = snapshot_path.replace("\\", "/").lstrip("/")
    if normalized.startswith("snapshots/"):
        normalized = normalized[len("snapshots/"):]

    segments = [quote(segment) for segment in normalized.split("/") if segment]
    if not segments:
        return None
    return "/snapshots/" + "/".join(segments)
