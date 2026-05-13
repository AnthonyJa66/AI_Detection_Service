"""WebSocket route initialization."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.manager import AlertMessage, WebSocketConnectionManager


logger = logging.getLogger("ai_detection_service.websocket.router")
router = APIRouter()
alert_connection_manager = WebSocketConnectionManager()
detection_connection_manager = WebSocketConnectionManager()


@router.websocket("/ws/alerts")
async def alert_socket(websocket: WebSocket) -> None:
    """Accept alert WebSocket clients for JSON alert pushes."""

    await alert_connection_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await alert_connection_manager.disconnect(websocket)
    except Exception as exc:
        logger.exception("Alert WebSocket connection failed: %s", exc)
        await alert_connection_manager.disconnect(websocket)


@router.websocket("/ws/detections")
async def detection_socket(websocket: WebSocket) -> None:
    """Initialize the real-time detection WebSocket endpoint."""

    await detection_connection_manager.connect(websocket)
    try:
        await websocket.send_json(
            {
                "type": "service.initialized",
                "message": "AI detection WebSocket endpoint is initialized.",
            }
        )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await detection_connection_manager.disconnect(websocket)
    except Exception as exc:
        logger.exception("Detection WebSocket connection failed: %s", exc)
        await detection_connection_manager.disconnect(websocket)


async def broadcast_alert(alert: AlertMessage) -> None:
    """Broadcast one JSON alert message to connected alert clients."""

    logger.info(
        "Broadcasting alert. camera_id=%s event_type=%s",
        alert.camera_id,
        alert.event_type,
    )
    await alert_connection_manager.broadcast(alert)
