"""Unit tests for server/websocket.py — WebSocketManager."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from server.websocket import WebSocketManager


class TestWebSocketManager:
    """Tests for WebSocketManager."""

    def test_init_empty(self):
        mgr = WebSocketManager()
        assert mgr.active_connections == []

    async def test_connect(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws)

        ws.accept.assert_awaited_once()
        assert ws in mgr.active_connections

    async def test_connect_multiple(self):
        mgr = WebSocketManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        assert len(mgr.active_connections) == 2

    def test_disconnect_existing(self):
        mgr = WebSocketManager()
        ws = MagicMock()
        mgr.active_connections.append(ws)

        mgr.disconnect(ws)
        assert ws not in mgr.active_connections

    def test_disconnect_nonexistent(self):
        mgr = WebSocketManager()
        ws = MagicMock()

        # Should not raise
        mgr.disconnect(ws)
        assert len(mgr.active_connections) == 0

    async def test_broadcast_no_connections(self):
        mgr = WebSocketManager()
        # Should not raise
        await mgr.broadcast({"type": "test"})

    async def test_broadcast_sends_to_all(self):
        mgr = WebSocketManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        mgr.active_connections = [ws1, ws2]

        await mgr.broadcast({"type": "test", "data": "hello"})

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()

        # Verify JSON content
        sent = ws1.send_text.call_args[0][0]
        import json
        data = json.loads(sent)
        assert data["type"] == "test"
        assert data["data"] == "hello"

    async def test_broadcast_removes_disconnected(self):
        mgr = WebSocketManager()
        ws_ok = AsyncMock()
        ws_broken = AsyncMock()
        ws_broken.send_text.side_effect = Exception("connection lost")

        mgr.active_connections = [ws_ok, ws_broken]

        await mgr.broadcast({"type": "test"})

        # Broken connection should be removed
        assert ws_broken not in mgr.active_connections
        assert ws_ok in mgr.active_connections

    async def test_broadcast_ensures_ascii_false(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        mgr.active_connections = [ws]

        await mgr.broadcast({"message": "日本語テスト"})

        sent = ws.send_text.call_args[0][0]
        assert "日本語テスト" in sent

    async def test_broadcast_uses_default_str(self):
        """Non-serializable values should use str() as default."""
        from pathlib import Path

        mgr = WebSocketManager()
        ws = AsyncMock()
        mgr.active_connections = [ws]

        await mgr.broadcast({"path": Path("/tmp/test")})

        ws.send_text.assert_awaited_once()
