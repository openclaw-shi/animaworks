from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger("animaworks.routes.internal")


class MessageSentNotification(BaseModel):
    from_person: str
    to_person: str
    content: str = ""


def create_internal_router() -> APIRouter:
    router = APIRouter()

    @router.post("/internal/message-sent")
    async def internal_message_sent(
        body: MessageSentNotification, request: Request
    ):
        """Notify the server that a message was sent via CLI.

        Triggers WebSocket broadcast and updates reply tracking so that
        selective archival (Fix 2) works for CLI-sent messages too.
        """
        ws = request.app.state.ws_manager
        await ws.broadcast(
            {
                "type": "person.interaction",
                "data": {
                    "from_person": body.from_person,
                    "to_person": body.to_person,
                    "type": "message",
                    "summary": body.content[:200],
                },
            }
        )

        # Update replied_to tracking if the sender is a managed person
        persons = request.app.state.persons
        person = persons.get(body.from_person)
        if person:
            person.agent.replied_to.add(body.to_person)

        return {"status": "ok"}

    return router
