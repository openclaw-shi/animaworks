"""Unit tests for server/app.py — FastAPI app factory and helpers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── _delegate ────────────────────────────────────────────


class TestDelegate:
    """Tests for the _delegate helper function."""

    async def test_delegate_success(self):
        from server.app import _delegate

        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.summary = "Task completed"
        mock_agent.run_cycle.return_value = mock_result

        mock_person = MagicMock()
        mock_person.agent = mock_agent

        persons = {"worker": mock_person}

        result = await _delegate(persons, "worker", "do stuff", None)

        assert result == "Task completed"
        mock_agent.run_cycle.assert_awaited_once_with(
            "do stuff", trigger="delegation:worker"
        )

    async def test_delegate_with_context(self):
        from server.app import _delegate

        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.summary = "Done"
        mock_agent.run_cycle.return_value = mock_result

        mock_person = MagicMock()
        mock_person.agent = mock_agent

        persons = {"worker": mock_person}

        result = await _delegate(persons, "worker", "do stuff", "some context")

        assert result == "Done"
        call_args = mock_agent.run_cycle.call_args
        assert "背景情報" in call_args[0][0]
        assert "some context" in call_args[0][0]
        assert "do stuff" in call_args[0][0]

    async def test_delegate_person_not_found(self):
        from server.app import _delegate

        result = await _delegate({}, "nonexistent", "task", None)

        assert "not found" in result


# ── create_app ───────────────────────────────────────────


class TestCreateApp:
    """Tests for create_app factory."""

    @patch("server.app.LifecycleManager")
    @patch("server.app.WebSocketManager")
    def test_create_app_no_persons_dir(self, mock_ws_cls, mock_lc_cls, tmp_path):
        from server.app import create_app

        persons_dir = tmp_path / "persons"
        shared_dir = tmp_path / "shared"
        # persons_dir does not exist

        mock_ws = MagicMock()
        mock_ws_cls.return_value = mock_ws
        mock_lc = MagicMock()
        mock_lc_cls.return_value = mock_lc

        app = create_app(persons_dir, shared_dir)

        assert app.state.persons == {}
        assert app.state.ws_manager is mock_ws
        assert app.state.lifecycle is mock_lc
        assert app.state.persons_dir == persons_dir
        assert app.state.shared_dir == shared_dir

    @patch("server.app.LifecycleManager")
    @patch("server.app.WebSocketManager")
    @patch("server.app.DigitalPerson")
    def test_create_app_with_persons(
        self, mock_dp_cls, mock_ws_cls, mock_lc_cls, tmp_path
    ):
        from server.app import create_app

        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        shared_dir = tmp_path / "shared"

        # Create a fake person directory with identity.md
        alice_dir = persons_dir / "alice"
        alice_dir.mkdir()
        (alice_dir / "identity.md").write_text("# Alice", encoding="utf-8")

        mock_person = MagicMock()
        mock_person.name = "alice"
        mock_dp_cls.return_value = mock_person

        mock_ws = MagicMock()
        mock_ws_cls.return_value = mock_ws
        mock_lc = MagicMock()
        mock_lc_cls.return_value = mock_lc

        app = create_app(persons_dir, shared_dir)

        assert "alice" in app.state.persons
        mock_lc.register_person.assert_called_once_with(mock_person)
        mock_person.set_delegate_fn.assert_called_once()
        mock_person.set_on_message_sent.assert_called_once()

    @patch("server.app.LifecycleManager")
    @patch("server.app.WebSocketManager")
    def test_create_app_skips_dirs_without_identity(
        self, mock_ws_cls, mock_lc_cls, tmp_path
    ):
        from server.app import create_app

        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        shared_dir = tmp_path / "shared"

        # Create dir without identity.md
        (persons_dir / "invalid").mkdir()

        mock_ws_cls.return_value = MagicMock()
        mock_lc_cls.return_value = MagicMock()

        app = create_app(persons_dir, shared_dir)

        assert app.state.persons == {}

    @patch("server.app.LifecycleManager")
    @patch("server.app.WebSocketManager")
    def test_create_app_skips_files_in_persons_dir(
        self, mock_ws_cls, mock_lc_cls, tmp_path
    ):
        from server.app import create_app

        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        shared_dir = tmp_path / "shared"

        # Create a file (not a directory)
        (persons_dir / "not_a_dir.txt").write_text("hello", encoding="utf-8")

        mock_ws_cls.return_value = MagicMock()
        mock_lc_cls.return_value = MagicMock()

        app = create_app(persons_dir, shared_dir)

        assert app.state.persons == {}


# ── lifespan ─────────────────────────────────────────────


class TestLifespan:
    """Tests for the lifespan context manager."""

    async def test_lifespan_start_and_stop(self):
        from server.app import lifespan

        mock_app = MagicMock()
        mock_lifecycle = MagicMock()
        mock_app.state.lifecycle = mock_lifecycle

        async with lifespan(mock_app):
            mock_lifecycle.start.assert_called_once()

        mock_lifecycle.shutdown.assert_called_once()
