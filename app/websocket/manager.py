"""WebSocket alert connection manager."""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket
from pydantic import BaseModel, Field


logger = logging.getLogger("ai_detection_service.websocket.manager")


class AlertMessage(BaseModel):
    """JSON alert message pushed to WebSocket clients."""

    camera_id: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    timestamp: int


class WebSocketConnectionManager:
    """Track connected WebSocket clients and broadcast alert messages."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            connection_count = len(self._connections)
        logger.info("WebSocket client connected. total=%s", connection_count)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            connection_count = len(self._connections)
        logger.info("WebSocket client disconnected. total=%s", connection_count)

    async def broadcast(self, alert: AlertMessage) -> None:
        """Broadcast an alert message to all connected clients."""

        payload = alert.model_dump()
        async with self._lock:
            connections = list(self._connections)

        if not connections:
            logger.debug("No WebSocket clients connected for alert broadcast.")
            return

        disconnected_clients: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception as exc:
                logger.warning("WebSocket alert push failed: %s", exc)
                disconnected_clients.append(websocket)

        if disconnected_clients:
            async with self._lock:
                for websocket in disconnected_clients:
                    self._connections.discard(websocket)

        logger.info(
            "Alert broadcast completed. camera_id=%s event_type=%s recipients=%s removed=%s",
            alert.camera_id,
            alert.event_type,
            len(connections),
            len(disconnected_clients),
        )

    @property
    def connection_count(self) -> int:
        return len(self._connections)
