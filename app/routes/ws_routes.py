from __future__ import annotations

from flask import Flask
from flask_sock import Sock

from app.services.websocket_manager import WebSocketConnectionManager


def init_websocket_routes(
    app: Flask,
    connection_manager: WebSocketConnectionManager,
) -> Sock:
    sock = Sock(app)

    @sock.route("/ws/alerts")
    @sock.route("/ws/alarms")
    def alarm_socket(ws) -> None:
        connection_manager.handle_client(ws)

    return sock
