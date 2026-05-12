"""WebSocket route initialization."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.manager import WebSocketConnectionManager


router = APIRouter()
connection_manager = WebSocketConnectionManager()


@router.websocket("/ws/detections")
async def detection_socket(websocket: WebSocket) -> None:
    """Initialize the real-time detection WebSocket endpoint."""

    await connection_manager.connect(websocket)
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
        connection_manager.disconnect(websocket)

