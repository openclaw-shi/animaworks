"""Unit tests for server/routes/system.py — System endpoints."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _make_test_app(
    persons: dict | None = None,
    persons_dir: Path | None = None,
    shared_dir: Path | None = None,
):
    from fastapi import FastAPI
    from server.routes.system import create_system_router

    app = FastAPI()
    app.state.persons = persons or {}
    app.state.persons_dir = persons_dir or Path("/tmp/fake/persons")
    app.state.shared_dir = shared_dir or Path("/tmp/fake/shared")

    # Mock lifecycle with scheduler
    lifecycle = MagicMock()
    scheduler = MagicMock()
    scheduler.running = True
    scheduler.get_jobs.return_value = []
    lifecycle.scheduler = scheduler
    app.state.lifecycle = lifecycle

    router = create_system_router()
    app.include_router(router, prefix="/api")
    return app


# ── GET /shared/users ────────────────────────────────────


class TestListSharedUsers:
    async def test_no_users_dir(self, tmp_path):
        shared_dir = tmp_path / "shared"
        # Don't create users dir
        app = _make_test_app(shared_dir=shared_dir)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/shared/users")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_with_users(self, tmp_path):
        shared_dir = tmp_path / "shared"
        users_dir = shared_dir / "users"
        users_dir.mkdir(parents=True)
        (users_dir / "alice").mkdir()
        (users_dir / "bob").mkdir()
        # Also create a file (should be ignored)
        (users_dir / "readme.txt").write_text("ignore", encoding="utf-8")

        app = _make_test_app(shared_dir=shared_dir)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/shared/users")
        data = resp.json()
        assert "alice" in data
        assert "bob" in data
        assert "readme.txt" not in data


# ── GET /system/status ───────────────────────────────────


class TestSystemStatus:
    async def test_status(self):
        alice = MagicMock()
        app = _make_test_app(persons={"alice": alice})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/system/status")
        data = resp.json()
        assert data["persons"] == 1
        assert data["scheduler_running"] is True
        assert data["jobs"] == []

    async def test_status_with_jobs(self):
        mock_job = MagicMock()
        mock_job.id = "hb-alice"
        mock_job.name = "heartbeat:alice"
        mock_job.next_run_time = "2026-01-01T12:00:00"

        app = _make_test_app()
        app.state.lifecycle.scheduler.get_jobs.return_value = [mock_job]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/system/status")
        data = resp.json()
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["id"] == "hb-alice"


# ── POST /system/reload ─────────────────────────────────


class TestReloadPersons:
    @patch("server.routes.system.DigitalPerson", create=True)
    async def test_reload_adds_new_persons(self, mock_dp_cls, tmp_path):
        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        shared_dir = tmp_path / "shared"

        # Create a new person on disk
        alice_dir = persons_dir / "alice"
        alice_dir.mkdir()
        (alice_dir / "identity.md").write_text("# Alice", encoding="utf-8")

        mock_person = MagicMock()
        mock_person.name = "alice"
        mock_dp_cls.return_value = mock_person

        app = _make_test_app(
            persons={},
            persons_dir=persons_dir,
            shared_dir=shared_dir,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/system/reload")

        data = resp.json()
        assert "alice" in data["added"]
        assert data["total"] == 1

    async def test_reload_removes_deleted_persons(self, tmp_path):
        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        shared_dir = tmp_path / "shared"

        old_person = MagicMock()
        app = _make_test_app(
            persons={"deleted": old_person},
            persons_dir=persons_dir,
            shared_dir=shared_dir,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/system/reload")

        data = resp.json()
        assert "deleted" in data["removed"]
        assert data["total"] == 0

    @patch("server.routes.system.DigitalPerson", create=True)
    async def test_reload_refreshes_existing(self, mock_dp_cls, tmp_path):
        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        shared_dir = tmp_path / "shared"

        alice_dir = persons_dir / "alice"
        alice_dir.mkdir()
        (alice_dir / "identity.md").write_text("# Alice", encoding="utf-8")

        mock_person = MagicMock()
        mock_person.name = "alice"
        mock_dp_cls.return_value = mock_person

        old_person = MagicMock()
        app = _make_test_app(
            persons={"alice": old_person},
            persons_dir=persons_dir,
            shared_dir=shared_dir,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/system/reload")

        data = resp.json()
        assert "alice" in data["refreshed"]

    async def test_reload_no_persons_dir(self, tmp_path):
        persons_dir = tmp_path / "nonexistent"
        shared_dir = tmp_path / "shared"

        app = _make_test_app(
            persons={},
            persons_dir=persons_dir,
            shared_dir=shared_dir,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/system/reload")
        data = resp.json()
        assert data["total"] == 0


# ── GET /activity/recent ─────────────────────────────────


class TestRecentActivity:
    async def test_activity_no_persons(self):
        app = _make_test_app(persons={})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/activity/recent")
        data = resp.json()
        assert data["events"] == []

    async def test_activity_with_hours_param(self):
        app = _make_test_app(persons={})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/activity/recent?hours=1")
        assert resp.status_code == 200

    async def test_activity_with_person_filter(self):
        app = _make_test_app(persons={"alice": MagicMock()})
        # Mock the person's person_dir to avoid filesystem access
        alice = app.state.persons["alice"]
        alice.person_dir = Path("/tmp/nonexistent")
        mc = MagicMock()
        mc.model = "test"
        alice.model_config = mc

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/activity/recent?person=alice")
        assert resp.status_code == 200
