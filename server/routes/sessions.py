from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import logging

from fastapi import APIRouter, Request

logger = logging.getLogger("animaworks.routes.sessions")


def create_sessions_router() -> APIRouter:
    router = APIRouter()

    @router.get("/persons/{name}/sessions")
    async def list_sessions(name: str, request: Request):
        """List all available sessions: active conversation, archives, episodes."""
        person = request.app.state.persons.get(name)
        if not person:
            return {"error": "Person not found"}
        from core.memory.conversation import ConversationMemory
        from core.memory.shortterm import ShortTermMemory

        # Active conversation
        conv = ConversationMemory(person.person_dir, person.model_config)
        conv_state = conv.load()
        active_conv = None
        if conv_state.turns or conv_state.compressed_summary:
            active_conv = {
                "exists": True,
                "turn_count": len(conv_state.turns),
                "total_turn_count": conv_state.total_turn_count,
                "last_timestamp": (
                    conv_state.turns[-1].timestamp if conv_state.turns else ""
                ),
                "first_timestamp": (
                    conv_state.turns[0].timestamp if conv_state.turns else ""
                ),
                "has_summary": bool(conv_state.compressed_summary),
            }

        # Archived sessions
        stm = ShortTermMemory(person.person_dir)
        archived = []
        archive_dir = stm._archive_dir
        if archive_dir.exists():
            for json_file in sorted(archive_dir.glob("*.json"), reverse=True):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    ts_str = json_file.stem
                    archived.append(
                        {
                            "id": ts_str,
                            "timestamp": data.get("timestamp", ts_str),
                            "trigger": data.get("trigger", ""),
                            "turn_count": data.get("turn_count", 0),
                            "context_usage_ratio": data.get(
                                "context_usage_ratio", 0
                            ),
                            "original_prompt_preview": data.get(
                                "original_prompt", ""
                            )[:200],
                            "has_markdown": (
                                archive_dir / f"{ts_str}.md"
                            ).exists(),
                        }
                    )
                except (json.JSONDecodeError, TypeError):
                    pass

        # Episodes
        episodes = []
        ep_dir = person.memory.episodes_dir
        if ep_dir.exists():
            for ep_file in sorted(ep_dir.glob("*.md"), reverse=True):
                content = ep_file.read_text(encoding="utf-8")
                episodes.append(
                    {"date": ep_file.stem, "preview": content[:200]}
                )

        # Transcripts (permanent message logs)
        transcripts = [
            {"date": date, "message_count": len(conv.load_transcript(date))}
            for date in conv.list_transcript_dates()
        ]

        return {
            "person": name,
            "active_conversation": active_conv,
            "archived_sessions": archived,
            "episodes": episodes,
            "transcripts": transcripts,
        }

    @router.get("/persons/{name}/sessions/{session_id}")
    async def get_session_detail(
        name: str, session_id: str, request: Request
    ):
        """Get archived session detail."""
        person = request.app.state.persons.get(name)
        if not person:
            return {"error": "Person not found"}
        from core.memory.shortterm import ShortTermMemory

        stm = ShortTermMemory(person.person_dir)
        archive_dir = stm._archive_dir
        json_path = archive_dir / f"{session_id}.json"
        md_path = archive_dir / f"{session_id}.md"

        if not json_path.exists():
            return {"error": "Session not found"}

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError):
            return {"error": "Session data corrupted"}

        markdown = ""
        if md_path.exists():
            markdown = md_path.read_text(encoding="utf-8")

        return {
            "person": name,
            "session_id": session_id,
            "data": data,
            "markdown": markdown,
        }

    @router.get("/persons/{name}/transcripts/{date}")
    async def get_transcript(name: str, date: str, request: Request):
        """Get full conversation transcript for a specific date."""
        person = request.app.state.persons.get(name)
        if not person:
            return {"error": "Person not found"}
        from core.memory.conversation import ConversationMemory

        conv = ConversationMemory(person.person_dir, person.model_config)
        messages = conv.load_transcript(date)
        return {
            "person": name,
            "date": date,
            "has_summary": False,
            "compressed_summary": "",
            "compressed_turn_count": 0,
            "turns": messages,
        }

    return router
