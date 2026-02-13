"""Unit tests for server/routes/websocket_route.py — WebSocket route."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes.websocket_route import create_websocket_router
from server.websocket import WebSocketManager


class TestWebSocketRoute:
    def test_websocket_connect_and_disconnect(self):
        app = FastAPI()
        ws_manager = WebSocketManager()
        app.state.ws_manager = ws_manager
        router = create_websocket_router()
        app.include_router(router)

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            assert len(ws_manager.active_connections) == 1

        # After disconnect
        assert len(ws_manager.active_connections) == 0

    def test_websocket_receives_messages(self):
        app = FastAPI()
        ws_manager = WebSocketManager()
        app.state.ws_manager = ws_manager
        router = create_websocket_router()
        app.include_router(router)

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            # Send a message (the route just receives and discards)
            ws.send_text("ping")
