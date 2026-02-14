"""Unit tests for core/person.py — DigitalPerson entity."""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from core.schemas import CycleResult, PersonStatus


# ── Helpers ───────────────────────────────────────────────


def _make_cycle_result(**kwargs) -> CycleResult:
    defaults = dict(trigger="test", action="responded", summary="done", duration_ms=100)
    defaults.update(kwargs)
    return CycleResult(**defaults)


# ── DigitalPerson construction ────────────────────────────


class TestDigitalPersonInit:
    def test_init(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore") as MockAgent, \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger") as MockMessenger:
            MockMM.return_value.read_model_config.return_value = MagicMock()
            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)

            assert dp.name == "alice"
            assert dp.person_dir == person_dir
            assert dp._status == "idle"
            assert dp._current_task == ""
            assert dp._last_heartbeat is None
            assert dp._last_activity is None


class TestDigitalPersonStatus:
    def test_status_property(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore") as MockAgent, \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger") as MockMessenger:
            MockMM.return_value.read_model_config.return_value = MagicMock()
            MockMessenger.return_value.unread_count.return_value = 5
            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)

            status = dp.status
            assert isinstance(status, PersonStatus)
            assert status.name == "alice"
            assert status.status == "idle"
            assert status.pending_messages == 5


class TestNeedsBootstrap:
    def test_needs_bootstrap_true(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"
        (person_dir / "bootstrap.md").write_text("bootstrap", encoding="utf-8")

        with patch("core.person.AgentCore"), \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"):
            MockMM.return_value.read_model_config.return_value = MagicMock()
            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            assert dp.needs_bootstrap is True

    def test_needs_bootstrap_false(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"
        # Ensure no bootstrap.md
        bp = person_dir / "bootstrap.md"
        if bp.exists():
            bp.unlink()

        with patch("core.person.AgentCore"), \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"):
            MockMM.return_value.read_model_config.return_value = MagicMock()
            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            assert dp.needs_bootstrap is False


# ── Callbacks ─────────────────────────────────────────────


class TestCallbacks:
    def test_set_on_message_sent(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore") as MockAgent, \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"):
            MockMM.return_value.read_model_config.return_value = MagicMock()
            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            fn = MagicMock()
            dp.set_on_message_sent(fn)
            dp.agent.set_on_message_sent.assert_called_once_with(fn)

    def test_set_on_lock_released(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore"), \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"):
            MockMM.return_value.read_model_config.return_value = MagicMock()
            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            fn = MagicMock()
            dp.set_on_lock_released(fn)
            assert dp._on_lock_released is fn


class TestNotifyLockReleased:
    def test_calls_callback(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore"), \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"):
            MockMM.return_value.read_model_config.return_value = MagicMock()
            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            fn = MagicMock()
            dp._on_lock_released = fn
            dp._notify_lock_released()
            fn.assert_called_once()

    def test_no_callback(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore"), \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"):
            MockMM.return_value.read_model_config.return_value = MagicMock()
            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            dp._on_lock_released = None
            dp._notify_lock_released()  # should not raise

    def test_exception_in_callback_is_caught(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore"), \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"):
            MockMM.return_value.read_model_config.return_value = MagicMock()
            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            dp._on_lock_released = MagicMock(side_effect=RuntimeError("boom"))
            dp._notify_lock_released()  # should not raise


# ── process_message ───────────────────────────────────────


class TestProcessMessage:
    async def test_process_message_returns_summary(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore") as MockAgent, \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"), \
             patch("core.person.ConversationMemory") as MockConv:
            MockMM.return_value.read_model_config.return_value = MagicMock()
            MockConv.return_value.compress_if_needed = AsyncMock()
            MockConv.return_value.build_chat_prompt.return_value = "prompt"
            MockConv.return_value.append_turn = MagicMock()
            MockConv.return_value.save = MagicMock()

            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            dp.agent.run_cycle = AsyncMock(return_value=_make_cycle_result(summary="Hello!"))

            result = await dp.process_message("Hi", from_person="human")
            assert result == "Hello!"
            assert dp._status == "idle"

    async def test_status_transitions(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore") as MockAgent, \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"), \
             patch("core.person.ConversationMemory") as MockConv:
            MockMM.return_value.read_model_config.return_value = MagicMock()
            MockConv.return_value.compress_if_needed = AsyncMock()
            MockConv.return_value.build_chat_prompt.return_value = "prompt"
            MockConv.return_value.append_turn = MagicMock()
            MockConv.return_value.save = MagicMock()

            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)

            observed_statuses = []

            async def mock_run_cycle(prompt, trigger="manual"):
                observed_statuses.append(dp._status)
                return _make_cycle_result()

            dp.agent.run_cycle = mock_run_cycle
            await dp.process_message("test")
            assert "thinking" in observed_statuses
            assert dp._status == "idle"

    async def test_exception_resets_status(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore"), \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"), \
             patch("core.person.ConversationMemory") as MockConv:
            MockMM.return_value.read_model_config.return_value = MagicMock()
            MockConv.return_value.compress_if_needed = AsyncMock()
            MockConv.return_value.build_chat_prompt.return_value = "prompt"

            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            dp.agent.run_cycle = AsyncMock(side_effect=RuntimeError("fail"))

            with pytest.raises(RuntimeError):
                await dp.process_message("test")
            assert dp._status == "idle"


# ── run_heartbeat ─────────────────────────────────────────


class TestRunHeartbeat:
    async def test_run_heartbeat(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore"), \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger") as MockMsg, \
             patch("core.person.load_prompt", return_value="prompt"):
            MockMM.return_value.read_model_config.return_value = MagicMock()
            MockMM.return_value.read_heartbeat_config.return_value = "checklist"
            MockMsg.return_value.has_unread.return_value = False

            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            dp.agent.run_cycle = AsyncMock(return_value=_make_cycle_result())
            dp.agent.reset_reply_tracking = MagicMock()
            dp.agent.replied_to = set()

            result = await dp.run_heartbeat()
            assert isinstance(result, CycleResult)
            assert dp._last_heartbeat is not None
            assert dp._status == "idle"


# ── run_cron_task ─────────────────────────────────────────


class TestRunCronTask:
    async def test_run_cron_task(self, data_dir, make_person):
        person_dir = make_person("alice")
        shared_dir = data_dir / "shared"

        with patch("core.person.AgentCore"), \
             patch("core.person.MemoryManager") as MockMM, \
             patch("core.person.Messenger"), \
             patch("core.person.load_prompt", return_value="cron prompt"):
            MockMM.return_value.read_model_config.return_value = MagicMock()

            from core.person import DigitalPerson
            dp = DigitalPerson(person_dir, shared_dir)
            dp.agent.run_cycle = AsyncMock(return_value=_make_cycle_result())

            result = await dp.run_cron_task("daily_report", "Generate report")
            assert isinstance(result, CycleResult)
            assert dp._status == "idle"
