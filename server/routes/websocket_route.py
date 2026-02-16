from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("animaworks.routes.websocket")


def create_websocket_router() -> APIRouter:
    """Create the WebSocket router with heartbeat-aware endpoint."""
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        ws_manager = websocket.app.state.ws_manager
        await ws_manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                await ws_manager.handle_client_message(websocket, data)
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected normally")
        except Exception:
            logger.warning("WebSocket connection lost unexpectedly", exc_info=True)
        finally:
            ws_manager.disconnect(websocket)

    return router
