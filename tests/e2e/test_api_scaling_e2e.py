"""E2E tests for API critical refactoring (scaling optimisations).

Validates the four CRITICAL fixes through the real FastAPI app stack:
1. load_model_config() — config resolution without live Person
2. sessions.py N+1 elimination — episodes/transcripts without full reads
3. persons.py parallel I/O — asyncio.gather for person detail
4. system.py activity endpoint — uses persons_dir/person_names
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


# ── Helpers ──────────────────────────────────────────────


def _create_app(tmp_path: Path, person_names: list[str] | None = None):
    """Build a real FastAPI app via create_app with mocked externals."""
    persons_dir = tmp_path / "persons"
    persons_dir.mkdir(parents=True, exist_ok=True)
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)

    with (
        patch("server.app.ProcessSupervisor") as mock_sup_cls,
        patch("server.app.load_config") as mock_cfg,
        patch("server.app.WebSocketManager") as mock_ws_cls,
    ):
        cfg = MagicMock()
        cfg.setup_complete = True
        mock_cfg.return_value = cfg

        supervisor = MagicMock()
        supervisor.get_all_status.return_value = {}
        supervisor.get_process_status.return_value = {"status": "stopped", "pid": None}
        mock_sup_cls.return_value = supervisor

        ws_manager = MagicMock()
        ws_manager.active_connections = []
        mock_ws_cls.return_value = ws_manager

        from server.app import create_app

        app = create_app(persons_dir, shared_dir)

    # Override person_names if specified (simulates reload after adding persons)
    if person_names is not None:
        app.state.person_names = person_names

    return app


def _create_person_on_disk(
    persons_dir: Path,
    name: str,
    *,
    identity: str = "# Test Person",
    episodes: list[str] | None = None,
    transcripts: dict[str, list[dict]] | None = None,
):
    """Create a person directory with optional episodes and transcripts."""
    person_dir = persons_dir / name
    person_dir.mkdir(parents=True, exist_ok=True)

    # Required subdirectories
    for subdir in ["episodes", "knowledge", "procedures", "state", "shortterm"]:
        (person_dir / subdir).mkdir(exist_ok=True)

    (person_dir / "identity.md").write_text(identity, encoding="utf-8")
    (person_dir / "injection.md").write_text("", encoding="utf-8")
    (person_dir / "permissions.md").write_text("", encoding="utf-8")

    # Episodes
    if episodes:
        ep_dir = person_dir / "episodes"
        for ep in episodes:
            (ep_dir / f"{ep}.md").write_text(
                f"# Episode {ep}\nSomething happened.", encoding="utf-8",
            )

    # Transcripts (JSONL files)
    if transcripts:
        transcript_dir = person_dir / "transcripts"
        transcript_dir.mkdir(exist_ok=True)
        for date, messages in transcripts.items():
            lines = [json.dumps(msg, ensure_ascii=False) for msg in messages]
            (transcript_dir / f"{date}.jsonl").write_text(
                "\n".join(lines) + "\n", encoding="utf-8",
            )

    return person_dir


# ── CRITICAL 1: load_model_config() ─────────────────────


class TestLoadModelConfigE2E:
    """Verify load_model_config works standalone (no live Person)."""

    def test_load_without_person_instance(self, data_dir):
        """load_model_config should produce a valid ModelConfig from config.json."""
        from core.config.models import load_model_config
        from core.schemas import ModelConfig

        person_dir = data_dir / "persons" / "standalone"
        person_dir.mkdir(parents=True, exist_ok=True)

        mc = load_model_config(person_dir)
        assert isinstance(mc, ModelConfig)
        assert mc.model  # non-empty string
        assert mc.max_tokens > 0

    def test_missing_config_returns_default(self, tmp_path, monkeypatch):
        """When config.json does not exist, return default ModelConfig."""
        from core.config.models import invalidate_cache, load_model_config
        from core.schemas import ModelConfig

        monkeypatch.setenv("ANIMAWORKS_DATA_DIR", str(tmp_path))
        invalidate_cache()

        person_dir = tmp_path / "persons" / "noconfig"
        person_dir.mkdir(parents=True)

        mc = load_model_config(person_dir)
        assert isinstance(mc, ModelConfig)

        invalidate_cache()


# ── CRITICAL 2: sessions.py N+1 elimination ─────────────


class TestSessionsN1E2E:
    """Verify sessions endpoint doesn't do N+1 reads on episodes/transcripts."""

    @patch("core.config.models.load_model_config")
    async def test_list_sessions_with_episodes(self, mock_lmc, tmp_path):
        """Episodes should be listed by filename only, not read."""
        persons_dir = tmp_path / "persons"
        _create_person_on_disk(
            persons_dir, "alice",
            episodes=["20260101", "20260102", "20260103"],
        )

        app = _create_app(tmp_path, person_names=["alice"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/persons/alice/sessions")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["episodes"]) == 3
        # Episodes should only contain date, no content preview
        for ep in data["episodes"]:
            assert "date" in ep
            assert "preview" not in ep

    @patch("core.config.models.load_model_config")
    async def test_list_sessions_with_transcripts(self, mock_lmc, tmp_path):
        """Transcripts should count lines without full JSON parse."""
        persons_dir = tmp_path / "persons"
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Bye"},
        ]
        _create_person_on_disk(
            persons_dir, "alice",
            transcripts={"2026-01-15": messages},
        )

        app = _create_app(tmp_path, person_names=["alice"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/persons/alice/sessions")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["transcripts"]) == 1
        assert data["transcripts"][0]["date"] == "2026-01-15"
        assert data["transcripts"][0]["message_count"] == 3


# ── CRITICAL 3: persons.py parallel I/O ─────────────────


class TestPersonsParallelIOE2E:
    """Verify person detail endpoint works with real filesystem reads."""

    async def test_person_detail_returns_all_fields(self, tmp_path):
        """GET /api/persons/{name} should return identity, state, file lists."""
        persons_dir = tmp_path / "persons"
        _create_person_on_disk(
            persons_dir, "alice",
            identity="# Alice\nShe is a test person.",
            episodes=["20260101"],
        )
        # Add a knowledge file
        (persons_dir / "alice" / "knowledge" / "facts.md").write_text(
            "# Facts\nAlice knows things.", encoding="utf-8",
        )

        app = _create_app(tmp_path, person_names=["alice"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/persons/alice")

        assert resp.status_code == 200
        data = resp.json()
        assert "identity" in data
        assert "status" in data
        # File lists should be populated from parallel I/O
        assert len(data["episode_files"]) >= 1
        assert len(data["knowledge_files"]) >= 1

    async def test_person_not_found(self, tmp_path):
        """GET /api/persons/{name} for non-existent person returns 404."""
        app = _create_app(tmp_path, person_names=[])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/persons/nobody")

        assert resp.status_code == 404


# ── CRITICAL 4: system.py activity — persons_dir/person_names ──


class TestActivityEndpointE2E:
    """Verify /api/activity/recent uses persons_dir, not app.state.persons."""

    async def test_activity_empty_returns_200(self, tmp_path):
        """Activity endpoint with no persons should return 200 with empty events."""
        app = _create_app(tmp_path, person_names=[])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/activity/recent")

        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []

    async def test_activity_with_person_returns_200(self, tmp_path):
        """Activity endpoint with a person should return 200 (no 500 error)."""
        persons_dir = tmp_path / "persons"
        _create_person_on_disk(persons_dir, "alice")

        app = _create_app(tmp_path, person_names=["alice"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/activity/recent?person=alice")

        # This previously returned 500 due to app.state.persons KeyError
        assert resp.status_code == 200

    async def test_activity_with_session_archive(self, tmp_path):
        """Activity should include session events from shortterm archives."""
        persons_dir = tmp_path / "persons"
        person_dir = _create_person_on_disk(persons_dir, "alice")

        # Create a session archive
        archive_dir = person_dir / "shortterm" / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        session = {
            "timestamp": "2026-02-15T10:00:00+00:00",
            "trigger": "heartbeat",
            "original_prompt": "Regular check-in",
            "turn_count": 3,
            "context_usage_ratio": 0.2,
        }
        (archive_dir / "20260215_100000.json").write_text(
            json.dumps(session), encoding="utf-8",
        )

        app = _create_app(tmp_path, person_names=["alice"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/activity/recent?hours=24")

        assert resp.status_code == 200
        data = resp.json()
        session_events = [e for e in data["events"] if e["type"] == "session"]
        assert len(session_events) >= 1
        assert session_events[0]["persons"] == ["alice"]
