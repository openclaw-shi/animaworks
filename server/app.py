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

from core.supervisor import ProcessSupervisor
from server.routes import create_router
from server.websocket import WebSocketManager

logger = logging.getLogger("animaworks.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start all Person processes
    await app.state.supervisor.start_all(app.state.person_names)
    logger.info("Server started with process isolation")
    yield
    # Shutdown all processes
    await app.state.supervisor.shutdown_all()
    logger.info("Server stopped")


def create_app(persons_dir: Path, shared_dir: Path) -> FastAPI:
    app = FastAPI(title="AnimaWorks", version="0.1.0", lifespan=lifespan)

    ws_manager = WebSocketManager()

    # Create run directory for sockets and PID files
    run_dir = Path.home() / ".animaworks" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Initialize ProcessSupervisor
    supervisor = ProcessSupervisor(
        persons_dir=persons_dir,
        shared_dir=shared_dir,
        run_dir=run_dir
    )

    # Discover person names from disk
    person_names: list[str] = []
    if persons_dir.exists():
        for person_dir in sorted(persons_dir.iterdir()):
            if person_dir.is_dir() and (person_dir / "identity.md").exists():
                person_names.append(person_dir.name)
                logger.info("Discovered person: %s", person_dir.name)

    app.state.supervisor = supervisor
    app.state.person_names = person_names
    app.state.ws_manager = ws_manager
    app.state.persons_dir = persons_dir
    app.state.shared_dir = shared_dir

    app.include_router(create_router())

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app