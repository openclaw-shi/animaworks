"""Unit tests for core/lifecycle.py — LifecycleManager and schedule parsing."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.lifecycle import (
    LifecycleManager,
    _DAY_MAP,
    _NTH_DAY_RANGE,
    _parse_cron_md,
    _parse_schedule,
)
from core.schemas import CronTask


# ── _parse_cron_md ────────────────────────────────────────


class TestParseCronMd:
    def test_empty_content(self):
        assert _parse_cron_md("") == []

    def test_single_task(self):
        content = """\
## 日次レポート（毎日 9:00 JST）
毎朝の報告を作成する。
"""
        tasks = _parse_cron_md(content)
        assert len(tasks) == 1
        assert tasks[0].name == "日次レポート"
        assert tasks[0].schedule == "毎日 9:00 JST"
        assert "毎朝の報告" in tasks[0].description

    def test_multiple_tasks(self):
        content = """\
## タスクA（毎日 8:00）
内容A

## タスクB（平日 17:00）
内容B
"""
        tasks = _parse_cron_md(content)
        assert len(tasks) == 2
        assert tasks[0].name == "タスクA"
        assert tasks[1].name == "タスクB"

    def test_task_without_schedule(self):
        content = """\
## No Schedule Here
Just a description.
"""
        tasks = _parse_cron_md(content)
        assert len(tasks) == 1
        assert tasks[0].name == "No Schedule Here"
        assert tasks[0].schedule == ""

    def test_parentheses_half_width(self):
        content = """\
## Report(毎日 10:00)
Description
"""
        tasks = _parse_cron_md(content)
        assert len(tasks) == 1
        assert tasks[0].schedule == "毎日 10:00"


# ── _parse_schedule ───────────────────────────────────────


class TestParseSchedule:
    def test_daily(self):
        trigger = _parse_schedule("毎日 9:00")
        assert trigger is not None

    def test_daily_with_timezone(self):
        trigger = _parse_schedule("毎日 9:00 JST")
        assert trigger is not None

    def test_weekday(self):
        trigger = _parse_schedule("平日 9:00")
        assert trigger is not None

    def test_weekly(self):
        trigger = _parse_schedule("毎週金曜 17:00")
        assert trigger is not None

    def test_biweekly(self):
        trigger = _parse_schedule("隔週金曜 17:00")
        assert trigger is not None

    def test_nth_weekday(self):
        trigger = _parse_schedule("第2火曜 10:00")
        assert trigger is not None

    def test_monthly_day(self):
        trigger = _parse_schedule("毎月1日 9:00")
        assert trigger is not None

    def test_monthly_last_day(self):
        trigger = _parse_schedule("毎月最終日 18:00")
        assert trigger is not None

    def test_standard_cron(self):
        trigger = _parse_schedule("*/5 * * * *")
        assert trigger is not None

    def test_invalid_schedule(self):
        trigger = _parse_schedule("whenever I feel like it")
        assert trigger is None

    def test_all_days_in_day_map(self):
        for jp_day, en_day in _DAY_MAP.items():
            trigger = _parse_schedule(f"毎週{jp_day} 10:00")
            assert trigger is not None

    def test_nth_day_ranges(self):
        for nth in (1, 2, 3, 4):
            assert nth in _NTH_DAY_RANGE

    def test_nth_5_returns_none(self):
        trigger = _parse_schedule("第5月曜 10:00")
        assert trigger is None


# ── LifecycleManager ──────────────────────────────────────


class TestLifecycleManager:
    def test_init(self):
        lm = LifecycleManager()
        assert lm.persons == {}
        assert lm._ws_broadcast is None

    def test_set_broadcast(self):
        lm = LifecycleManager()
        fn = AsyncMock()
        lm.set_broadcast(fn)
        assert lm._ws_broadcast is fn

    def test_register_person(self):
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "alice"
        person.memory.read_heartbeat_config.return_value = ""
        person.memory.read_cron_config.return_value = ""
        person.set_on_lock_released = MagicMock()

        lm.register_person(person)
        assert "alice" in lm.persons
        person.set_on_lock_released.assert_called_once()

    def test_unregister_person(self):
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "alice"
        person.memory.read_heartbeat_config.return_value = ""
        person.memory.read_cron_config.return_value = ""
        person.set_on_lock_released = MagicMock()

        lm.register_person(person)
        lm.unregister_person("alice")
        assert "alice" not in lm.persons

    def test_unregister_nonexistent(self):
        lm = LifecycleManager()
        lm.unregister_person("nobody")  # should not raise


class TestHeartbeatWrapper:
    async def test_heartbeat_with_broadcast(self):
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "alice"
        person.run_heartbeat = AsyncMock(return_value=MagicMock())
        person.run_heartbeat.return_value.model_dump.return_value = {}
        lm.persons["alice"] = person

        broadcast = AsyncMock()
        lm._ws_broadcast = broadcast

        await lm._heartbeat_wrapper("alice")
        person.run_heartbeat.assert_called_once()
        broadcast.assert_called_once()

    async def test_heartbeat_no_person(self):
        lm = LifecycleManager()
        # Should return silently
        await lm._heartbeat_wrapper("nobody")


class TestCronWrapper:
    async def test_cron_with_broadcast(self):
        import asyncio

        lm = LifecycleManager()
        person = MagicMock()
        person.name = "alice"
        person.run_cron_task = AsyncMock(return_value=MagicMock())
        person.run_cron_task.return_value.model_dump.return_value = {}
        lm.persons["alice"] = person

        broadcast = AsyncMock()
        lm._ws_broadcast = broadcast

        await lm._cron_wrapper("alice", "daily_report", "Generate report")
        # _cron_wrapper creates a background task; let it run
        await asyncio.sleep(0)
        person.run_cron_task.assert_called_once_with("daily_report", "Generate report")
        broadcast.assert_called_once()

    async def test_cron_no_person(self):
        lm = LifecycleManager()
        await lm._cron_wrapper("nobody", "task", "desc")


class TestSetupHeartbeat:
    def test_parses_interval_from_config(self):
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "alice"
        person.memory.read_heartbeat_config.return_value = "巡回間隔: 15分"
        person.memory.read_cron_config.return_value = ""
        person.set_on_lock_released = MagicMock()

        lm.register_person(person)
        # Job should be registered
        jobs = lm.scheduler.get_jobs()
        assert any(j.id == "alice_heartbeat" for j in jobs)

    def test_parses_active_hours(self):
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "bob"
        person.memory.read_heartbeat_config.return_value = "稼働時間: 8:00 - 20:00"
        person.memory.read_cron_config.return_value = ""
        person.set_on_lock_released = MagicMock()

        lm.register_person(person)
        jobs = lm.scheduler.get_jobs()
        assert any(j.id == "bob_heartbeat" for j in jobs)


class TestMessageTriggeredHeartbeat:
    async def test_triggered_heartbeat_success(self):
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "alice"
        person.run_heartbeat = AsyncMock(return_value=MagicMock())
        person.run_heartbeat.return_value.model_dump.return_value = {}
        lm.persons["alice"] = person
        lm._pending_triggers.add("alice")

        await lm._message_triggered_heartbeat("alice")
        person.run_heartbeat.assert_called_once()
        assert "alice" not in lm._pending_triggers

    async def test_triggered_heartbeat_no_person(self):
        lm = LifecycleManager()
        lm._pending_triggers.add("nobody")
        await lm._message_triggered_heartbeat("nobody")
        assert "nobody" not in lm._pending_triggers


class TestOnPersonLockReleased:
    async def test_triggers_heartbeat_when_deferred(self):
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "alice"
        person.messenger.has_unread.return_value = True
        lm.persons["alice"] = person
        lm._deferred_inbox.add("alice")

        with patch.object(lm, "_message_triggered_heartbeat", new_callable=AsyncMock):
            await lm._on_person_lock_released("alice")
            assert "alice" not in lm._deferred_inbox

    async def test_no_action_when_not_deferred(self):
        lm = LifecycleManager()
        # alice not in _deferred_inbox
        await lm._on_person_lock_released("alice")


class TestLifecycleStartShutdown:
    async def test_start_and_shutdown(self):
        lm = LifecycleManager()
        lm.start()
        assert lm._inbox_watcher_task is not None
        assert lm.scheduler.running
        lm.shutdown()
        # After shutdown, the inbox watcher task should be in cancelling state
        assert lm._inbox_watcher_task.cancelling() > 0 or lm._inbox_watcher_task.cancelled()
