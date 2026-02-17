from __future__ import annotations
# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from server.dependencies import get_anima
from server.events import emit, emit_notification

logger = logging.getLogger("animaworks.routes.chat")

MAX_CHAT_MESSAGE_SIZE = 10 * 1024 * 1024  # 10MB


class ChatRequest(BaseModel):
    message: str
    from_person: str = "human"


class ChatResponse(BaseModel):
    response: str
    anima: str


# ── SSE Helpers ───────────────────────────────────────────────

def _format_sse(event: str, payload: dict[str, Any]) -> str:
    """Format a single SSE frame."""
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n"



# ── Emotion Extraction ────────────────────────────────────

from core.schemas import VALID_EMOTIONS

_EMOTION_PATTERN = re.compile(
    r'<!--\s*emotion:\s*(\{.*?\})\s*-->', re.DOTALL,
)


def extract_emotion(response_text: str) -> tuple[str, str]:
    """Extract emotion metadata from LLM response text.

    The LLM appends ``<!-- emotion: {"emotion": "smile"} -->`` to its
    response.  This function strips the tag and returns the clean text
    plus the emotion name.

    Returns:
        (clean_text, emotion) where *emotion* falls back to ``"neutral"``
        when missing or invalid.
    """
    match = _EMOTION_PATTERN.search(response_text)
    if not match:
        return response_text, "neutral"

    clean_text = _EMOTION_PATTERN.sub("", response_text).rstrip()

    try:
        meta = json.loads(match.group(1))
        emotion = meta.get("emotion", "neutral")
        if emotion not in VALID_EMOTIONS:
            emotion = "neutral"
        return clean_text, emotion
    except (json.JSONDecodeError, AttributeError):
        return clean_text, "neutral"


def _handle_chunk(
    chunk: dict[str, Any],
    *,
    request: Request | None = None,
    anima_name: str | None = None,
) -> tuple[str | None, str]:
    """Map a stream chunk to an SSE event name and extract response text.

    Args:
        chunk: Stream chunk dictionary.
        request: FastAPI Request (optional, for emitting WebSocket events).
        anima_name: Anima name (optional, for WebSocket event data).

    Returns:
        Tuple of (sse_frame_or_None, accumulated_response_text).
    """
    event_type = chunk.get("type", "unknown")

    if event_type == "text_delta":
        return _format_sse("text_delta", {"text": chunk["text"]}), ""

    if event_type == "tool_start":
        return _format_sse("tool_start", {
            "tool_name": chunk["tool_name"],
            "tool_id": chunk["tool_id"],
        }), ""

    if event_type == "tool_end":
        return _format_sse("tool_end", {
            "tool_id": chunk["tool_id"],
            "tool_name": chunk.get("tool_name", ""),
        }), ""

    if event_type == "chain_start":
        return _format_sse("chain_start", {"chain": chunk["chain"]}), ""

    if event_type == "bootstrap_start":
        if request and anima_name:
            import asyncio
            asyncio.ensure_future(emit(
                request, "anima.bootstrap",
                {"name": anima_name, "status": "started"},
            ))
        return _format_sse("bootstrap", {"status": "started"}), ""

    if event_type == "bootstrap_complete":
        if request and anima_name:
            import asyncio
            asyncio.ensure_future(emit(
                request, "anima.bootstrap",
                {"name": anima_name, "status": "completed"},
            ))
        return _format_sse("bootstrap", {"status": "completed"}), ""

    if event_type == "bootstrap_busy":
        return _format_sse("bootstrap", {
            "status": "busy",
            "message": chunk.get("message", "初期化中です"),
        }), ""

    if event_type == "heartbeat_relay_start":
        return _format_sse("heartbeat_relay_start", {
            "message": chunk.get("message", "処理中です"),
        }), ""

    if event_type == "heartbeat_relay":
        return _format_sse("heartbeat_relay", {
            "text": chunk.get("text", ""),
        }), chunk.get("text", "")

    if event_type == "heartbeat_relay_done":
        return _format_sse("heartbeat_relay_done", {}), ""

    if event_type == "notification_sent":
        # Broadcast notification to all WebSocket clients (with queue support)
        if request:
            import asyncio
            notif_data = chunk.get("data", {})
            asyncio.ensure_future(
                emit_notification(request, notif_data)
            )
        return None, ""

    if event_type == "cycle_done":
        cycle_result = chunk.get("cycle_result", {})
        response_text = cycle_result.get("summary", "")
        # Extract emotion from response and include in done event
        clean_text, emotion = extract_emotion(response_text)
        cycle_result["summary"] = clean_text
        cycle_result["emotion"] = emotion
        return _format_sse("done", cycle_result), clean_text

    if event_type == "error":
        error_payload: dict[str, Any] = {
            "message": chunk.get("message", "Unknown error"),
        }
        if "code" in chunk:
            error_payload["code"] = chunk["code"]
        return _format_sse("error", error_payload), ""

    return None, ""


async def _stream_events(
    anima: Any,
    name: str,
    body: ChatRequest,
    request: Request,
) -> AsyncIterator[str]:
    """Async generator that yields SSE frames for a streaming chat session."""
    full_response = ""
    try:
        await emit(request, "anima.status", {"name": name, "status": "thinking"})

        async for chunk in anima.process_message_stream(
            body.message, from_person=body.from_person
        ):
            frame, response_text = _handle_chunk(
                chunk, request=request, anima_name=name,
            )
            if response_text:
                full_response = response_text
            if frame:
                yield frame

    except Exception:
        logger.exception("SSE stream error for anima=%s", name)
        yield _format_sse("error", {"code": "STREAM_ERROR", "message": "Internal server error"})

    finally:
        await emit(request, "anima.status", {"name": name, "status": "idle"})


# ── Router ────────────────────────────────────────────────────

def create_chat_router() -> APIRouter:
    router = APIRouter()

    @router.post("/animas/{name}/chat")
    async def chat(name: str, body: ChatRequest, request: Request):
        logger.info("chat_request anima=%s user=%s msg_len=%d", name, body.from_person, len(body.message))
        supervisor = request.app.state.supervisor

        # Guard: reject if anima is bootstrapping
        if supervisor.is_bootstrapping(name):
            return JSONResponse(
                {"error": "現在キャラクターを作成中です。完了までお待ちください。"},
                status_code=503,
            )

        # Guard: reject oversized messages
        message_size = len(body.message.encode("utf-8"))
        if message_size > MAX_CHAT_MESSAGE_SIZE:
            return JSONResponse(
                {"error": f"メッセージが大きすぎます（{message_size // 1024 // 1024}MB / 上限10MB）"},
                status_code=413,
            )

        await emit(request, "anima.status", {"name": name, "status": "thinking"})

        try:
            # Send IPC request to Anima process
            result = await supervisor.send_request(
                anima_name=name,
                method="process_message",
                params={
                    "message": body.message,
                    "from_person": body.from_person
                },
                timeout=60.0
            )

            response = result.get("response", "")
            clean_response, _ = extract_emotion(response)

            # Broadcast any queued notifications from this cycle
            for notif in result.get("notifications", []):
                await emit_notification(request, notif)

            await emit(request, "anima.status", {"name": name, "status": "idle"})

            logger.info("chat_response anima=%s response_len=%d", name, len(clean_response))
            return ChatResponse(response=clean_response, anima=name)

        except KeyError:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Anima not found: {name}")
        except ValueError as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=str(e))
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for chat response from anima=%s", name)
            return JSONResponse(
                {"error": "Request timed out"}, status_code=504,
            )
        except RuntimeError as e:
            logger.exception("Runtime error in chat for anima=%s", name)
            return JSONResponse(
                {"error": f"Internal server error: {e}"}, status_code=500,
            )

    @router.post("/animas/{name}/greet")
    async def greet(name: str, request: Request):
        """Generate a greeting when user clicks the character.

        Returns cached response if called within the 1-hour cooldown.
        Non-streaming, returns a single JSON response.
        """
        supervisor = request.app.state.supervisor

        # Guard: reject if anima is bootstrapping
        if supervisor.is_bootstrapping(name):
            return JSONResponse(
                {"error": "現在キャラクターを作成中です。完了までお待ちください。"},
                status_code=503,
            )

        try:
            result = await supervisor.send_request(
                anima_name=name,
                method="greet",
                params={},
                timeout=60.0,
            )

            return {
                "response": result.get("response", ""),
                "emotion": result.get("emotion", "neutral"),
                "cached": result.get("cached", False),
                "anima": name,
            }

        except KeyError:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Anima not found: {name}")
        except ValueError as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=str(e))
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for greet response from anima=%s", name)
            return JSONResponse(
                {"error": "Request timed out"}, status_code=504,
            )
        except RuntimeError as e:
            logger.exception("Runtime error in greet for anima=%s", name)
            return JSONResponse(
                {"error": f"Internal server error: {e}"}, status_code=500,
            )

    @router.post("/animas/{name}/chat/stream")
    async def chat_stream(name: str, body: ChatRequest, request: Request):
        """Stream chat response via SSE over IPC."""
        logger.info("chat_stream_request anima=%s user=%s msg_len=%d", name, body.from_person, len(body.message))
        supervisor = request.app.state.supervisor

        # Verify anima exists before starting the stream
        if name not in supervisor.processes:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Anima not found: {name}")

        # Guard: reject oversized messages
        message_size = len(body.message.encode("utf-8"))
        if message_size > MAX_CHAT_MESSAGE_SIZE:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=413,
                detail=f"メッセージが大きすぎます（{message_size // 1024 // 1024}MB / 上限10MB）",
            )

        # Guard: return immediately if anima is bootstrapping
        if supervisor.is_bootstrapping(name):
            async def _bootstrap_busy() -> AsyncIterator[str]:
                yield _format_sse("bootstrap", {
                    "status": "busy",
                    "message": "現在キャラクターを作成中です。完了までお待ちください。",
                })

            return StreamingResponse(
                _bootstrap_busy(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        async def _ipc_stream_events() -> AsyncIterator[str]:
            """Async generator that converts IPC stream to SSE frames."""
            full_response = ""
            try:
                await emit(request, "anima.status", {"name": name, "status": "thinking"})

                from core.config import load_config
                _config = load_config()
                _timeout = float(_config.server.ipc_stream_timeout)

                async for ipc_response in supervisor.send_request_stream(
                    anima_name=name,
                    method="process_message",
                    params={
                        "message": body.message,
                        "from_person": body.from_person,
                        "stream": True,
                    },
                    timeout=_timeout,
                ):
                    if ipc_response.done:
                        # Final response with full result
                        result = ipc_response.result or {}
                        full_response = result.get("response", full_response)
                        cycle_result = result.get("cycle_result", {})
                        # Extract emotion from response
                        summary = cycle_result.get("summary", full_response)
                        clean_text, emotion = extract_emotion(summary)
                        cycle_result["summary"] = clean_text
                        cycle_result["emotion"] = emotion
                        full_response = clean_text
                        yield _format_sse("done", cycle_result or {"summary": clean_text, "emotion": emotion})
                        break

                    if ipc_response.chunk:
                        # Parse the chunk JSON from the IPC layer
                        try:
                            chunk_data = json.loads(ipc_response.chunk)

                            # Keep-alive chunks → SSE comment (invisible to client parser)
                            if chunk_data.get("type") == "keepalive":
                                yield ": keepalive\n\n"
                                continue

                            frame, response_text = _handle_chunk(
                                chunk_data,
                                request=request,
                                anima_name=name,
                            )
                            if response_text:
                                full_response = response_text
                            if frame:
                                yield frame
                        except json.JSONDecodeError:
                            # Raw text chunk fallback
                            full_response += ipc_response.chunk
                            yield _format_sse("text_delta", {"text": ipc_response.chunk})
                        continue

                    # Fallback: non-streaming IPC response (result without done flag)
                    if ipc_response.result:
                        result = ipc_response.result
                        full_response = result.get("response", "")
                        cycle_result = result.get("cycle_result", {})
                        summary = cycle_result.get("summary", full_response)
                        clean_text, emotion = extract_emotion(summary)
                        cycle_result["summary"] = clean_text
                        cycle_result["emotion"] = emotion
                        full_response = clean_text
                        yield _format_sse("done", cycle_result or {"summary": clean_text, "emotion": emotion})
                        break

            except ValueError as e:
                logger.error("IPC stream error for anima=%s: %s", name, e)
                yield _format_sse("error", {"code": "IPC_ERROR", "message": str(e)})
            except KeyError:
                logger.error("Anima not found during stream: %s", name)
                yield _format_sse("error", {"code": "ANIMA_NOT_FOUND", "message": f"Anima not found: {name}"})
            except TimeoutError:
                logger.error("IPC stream timeout for anima=%s", name)
                yield _format_sse("error", {"code": "IPC_TIMEOUT", "message": "応答がタイムアウトしました"})
            except Exception:
                logger.exception("IPC stream error for anima=%s", name)
                yield _format_sse("error", {"code": "STREAM_ERROR", "message": "Internal server error"})
            finally:
                await emit(request, "anima.status", {"name": name, "status": "idle"})

        return StreamingResponse(
            _ipc_stream_events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
