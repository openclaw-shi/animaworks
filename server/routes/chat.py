from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("animaworks.routes.chat")


class ChatRequest(BaseModel):
    message: str
    from_person: str = "human"


class ChatResponse(BaseModel):
    response: str
    person: str


def create_chat_router() -> APIRouter:
    router = APIRouter()

    @router.post("/persons/{name}/chat")
    async def chat(name: str, body: ChatRequest, request: Request):
        person = request.app.state.persons.get(name)
        if not person:
            return {"error": "Person not found"}

        ws = request.app.state.ws_manager
        await ws.broadcast(
            {"type": "person.status", "data": {"name": name, "status": "thinking"}}
        )

        response = await person.process_message(body.message, from_person=body.from_person)

        await ws.broadcast(
            {"type": "person.status", "data": {"name": name, "status": "idle"}}
        )
        await ws.broadcast(
            {"type": "chat.response", "data": {"name": name, "message": response}}
        )

        return ChatResponse(response=response, person=name)

    @router.post("/persons/{name}/chat/stream")
    async def chat_stream(name: str, body: ChatRequest, request: Request):
        person = request.app.state.persons.get(name)
        if not person:
            return {"error": "Person not found"}

        ws = request.app.state.ws_manager

        async def event_generator():
            full_response = ""
            try:
                await ws.broadcast(
                    {"type": "person.status", "data": {"name": name, "status": "thinking"}}
                )

                async for chunk in person.process_message_stream(
                    body.message, from_person=body.from_person
                ):
                    event_type = chunk.get("type", "unknown")

                    if event_type == "text_delta":
                        data = json.dumps({"text": chunk["text"]}, ensure_ascii=False)
                        yield f"event: text_delta\ndata: {data}\n\n"

                    elif event_type == "tool_start":
                        data = json.dumps(
                            {"tool_name": chunk["tool_name"], "tool_id": chunk["tool_id"]},
                            ensure_ascii=False,
                        )
                        yield f"event: tool_start\ndata: {data}\n\n"

                    elif event_type == "tool_end":
                        data = json.dumps(
                            {"tool_id": chunk["tool_id"], "tool_name": chunk.get("tool_name", "")},
                            ensure_ascii=False,
                        )
                        yield f"event: tool_end\ndata: {data}\n\n"

                    elif event_type == "chain_start":
                        data = json.dumps({"chain": chunk["chain"]}, ensure_ascii=False)
                        yield f"event: chain_start\ndata: {data}\n\n"

                    elif event_type == "cycle_done":
                        cycle_result = chunk.get("cycle_result", {})
                        full_response = cycle_result.get("summary", "")
                        data = json.dumps(cycle_result, ensure_ascii=False, default=str)
                        yield f"event: done\ndata: {data}\n\n"

                    elif event_type == "error":
                        data = json.dumps(
                            {"message": chunk.get("message", "Unknown error")},
                            ensure_ascii=False,
                        )
                        yield f"event: error\ndata: {data}\n\n"

                if full_response:
                    await ws.broadcast(
                        {"type": "chat.response", "data": {"name": name, "message": full_response}}
                    )

            except Exception:
                logger.exception("SSE stream error for person=%s", name)
                data = json.dumps({"message": "Internal server error"}, ensure_ascii=False)
                yield f"event: error\ndata: {data}\n\n"

            finally:
                await ws.broadcast(
                    {"type": "person.status", "data": {"name": name, "status": "idle"}}
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
