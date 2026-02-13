from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.lifecycle import LifecycleManager
from core.person import DigitalPerson
from server.routes import create_router
from server.websocket import WebSocketManager

logger = logging.getLogger("animaworks.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.lifecycle.start()
    logger.info("Server started")
    yield
    app.state.lifecycle.shutdown()
    logger.info("Server stopped")


async def _delegate(
    persons: dict[str, DigitalPerson],
    target_name: str,
    task: str,
    context: str | None,
) -> str:
    """Execute a delegated task on the target person's AgentCore.

    Called synchronously (awaited) by the delegating commander.
    Bypasses the Person-level lock to avoid deadlock — concurrency
    is handled by AgentCore's own ``_agent_lock``.
    """
    target = persons.get(target_name)
    if not target:
        return f"Error: Person '{target_name}' not found"

    prompt = task
    if context:
        prompt = f"## 背景情報\n{context}\n\n## 指示\n{task}"

    result = await target.agent.run_cycle(prompt, trigger=f"delegation:{target_name}")
    return result.summary


def create_app(persons_dir: Path, shared_dir: Path) -> FastAPI:
    app = FastAPI(title="AnimaWorks", version="0.1.0", lifespan=lifespan)

    ws_manager = WebSocketManager()
    lifecycle = LifecycleManager()
    lifecycle.set_broadcast(ws_manager.broadcast)

    persons: dict[str, DigitalPerson] = {}
    if persons_dir.exists():
        for person_dir in sorted(persons_dir.iterdir()):
            if person_dir.is_dir() and (person_dir / "identity.md").exists():
                person = DigitalPerson(person_dir, shared_dir)
                persons[person.name] = person
                lifecycle.register_person(person)
                logger.info("Loaded person: %s", person.name)

    # Inject delegate callbacks so commanders can delegate to subordinates
    for person in persons.values():
        person.set_delegate_fn(
            lambda name, task, ctx=None, _p=persons: _delegate(_p, name, task, ctx)
        )

    # Inject message-sent callback to broadcast person.interaction via WebSocket
    def _on_message_sent(from_person: str, to_person: str, content: str) -> None:
        import asyncio

        event = {
            "type": "person.interaction",
            "data": {
                "from_person": from_person,
                "to_person": to_person,
                "type": "message",
                "summary": content[:200],
            },
        }
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(ws_manager.broadcast(event))
        except RuntimeError:
            logger.debug("No event loop for person.interaction broadcast")

    for person in persons.values():
        person.set_on_message_sent(_on_message_sent)

    app.state.persons = persons
    app.state.lifecycle = lifecycle
    app.state.ws_manager = ws_manager
    app.state.persons_dir = persons_dir
    app.state.shared_dir = shared_dir

    app.include_router(create_router())

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app