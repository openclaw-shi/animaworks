from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from server.dependencies import get_person

logger = logging.getLogger("animaworks.routes.persons")


def _read_appearance(person_dir: Path) -> dict | None:
    """Read appearance.json from a person directory."""
    path = person_dir / "appearance.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if data else None
    except (json.JSONDecodeError, OSError):
        return None


def create_persons_router() -> APIRouter:
    router = APIRouter()

    @router.get("/persons")
    async def list_persons(request: Request):
        persons = request.app.state.persons
        result = []
        for p in persons.values():
            data = p.status.model_dump()
            mc = p.model_config
            data["supervisor"] = mc.supervisor
            data["appearance"] = _read_appearance(p.person_dir)
            result.append(data)
        return result

    @router.get("/persons/{name}")
    async def get_person_detail(name: str, person=Depends(get_person)):
        return {
            "status": person.status.model_dump(),
            "identity": person.memory.read_identity(),
            "injection": person.memory.read_injection(),
            "state": person.memory.read_current_state(),
            "pending": person.memory.read_pending(),
            "knowledge_files": person.memory.list_knowledge_files(),
            "episode_files": person.memory.list_episode_files(),
            "procedure_files": person.memory.list_procedure_files(),
        }

    @router.post("/persons/{name}/trigger")
    async def trigger_heartbeat(name: str, person=Depends(get_person)):
        result = await person.run_heartbeat()
        return result.model_dump()

    return router
