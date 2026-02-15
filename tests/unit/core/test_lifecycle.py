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

    def test_llm_type_explicit(self):
        """Test explicit LLM-type task parsing."""
        content = """\
## 業務計画（毎日 9:00 JST）
type: llm
長期記憶から昨日の進捗を確認する。
"""
        tasks = _parse_cron_md(content)
        assert len(tasks) == 1
        assert tasks[0].type == "llm"
        assert tasks[0].name == "業務計画"
        assert "長期記憶" in tasks[0].description
        assert tasks[0].command is None
        assert tasks[0].tool is None

    def test_llm_type_default(self):
        """Test LLM-type task with default type (no explicit type field)."""
        content = """\
## 日次報告（毎日 17:00）
報告書を作成する。
"""
        tasks = _parse_cron_md(content)
        assert len(tasks) == 1
        assert tasks[0].type == "llm"  # Default type
        assert "報告書" in tasks[0].description

    def test_command_type_bash(self):
        """Test command-type task with bash command."""
        content = """\
## バックアップ実行（毎日 2:00 JST）
type: command
command: /usr/local/bin/backup.sh
"""
        tasks = _parse_cron_md(content)
        assert len(tasks) == 1
        assert tasks[0].type == "command"
        assert tasks[0].command == "/usr/local/bin/backup.sh"
        assert tasks[0].tool is None
        assert tasks[0].args is None

    def test_command_type_tool_with_args(self):
        """Test command-type task with internal tool and YAML args."""
        content = """\
## Slack通知（平日 9:00 JST）
type: command
tool: slack_send_message
args:
  channel: "#general"
  message: "おはようございます！"
"""
        tasks = _parse_cron_md(content)
        assert len(tasks) == 1
        assert tasks[0].type == "command"
        assert tasks[0].tool == "slack_send_message"
        assert tasks[0].command is None
        assert tasks[0].args is not None
        assert tasks[0].args["channel"] == "#general"
        assert tasks[0].args["message"] == "おはようございます！"

    def test_mixed_types(self):
        """Test parsing multiple tasks with different types."""
        content = """\
## 業務計画（毎日 9:00）
type: llm
計画を立てる。

## バックアップ（毎日 2:00）
type: command
command: /bin/backup.sh

## 通知送信（平日 10:00）
type: command
tool: send_notification
args:
  message: "Start working"
"""
        tasks = _parse_cron_md(content)
        assert len(tasks) == 3
        assert tasks[0].type == "llm"
        assert tasks[1].type == "command"
        assert tasks[1].command == "/bin/backup.sh"
        assert tasks[2].type == "command"
        assert tasks[2].tool == "send_notification"
        assert tasks[2].args["message"] == "Start working"


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

        # Create CronTask object (LLM type)
        task = CronTask(
            name="daily_report",
            schedule="毎日 9:00",
            type="llm",
            description="Generate report",
        )
        await lm._cron_wrapper("alice", task)
        # _cron_wrapper creates a background task; let it run
        await asyncio.sleep(0)
        person.run_cron_task.assert_called_once_with("daily_report", "Generate report")
        broadcast.assert_called_once()

    async def test_cron_no_person(self):
        lm = LifecycleManager()
        task = CronTask(name="task", schedule="毎日 10:00", description="desc")
        await lm._cron_wrapper("nobody", task)


class TestSetupHeartbeat:
    def test_interval_is_always_30_minutes(self):
        """Heartbeat interval is fixed at 30 minutes regardless of config."""
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "alice"
        # Even if config says 15 minutes, interval should remain 30
        person.memory.read_heartbeat_config.return_value = "巡回間隔: 15分"
        person.memory.read_cron_config.return_value = ""
        person.set_on_lock_released = MagicMock()

        lm.register_person(person)
        jobs = lm.scheduler.get_jobs()
        hb_job = next(j for j in jobs if j.id == "alice_heartbeat")
        # CronTrigger fields: verify minute is */30
        assert str(hb_job.trigger).find("*/30") != -1

    def test_interval_fixed_with_5min_config(self):
        """Ensure 5-minute config is ignored; interval stays 30."""
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "bob"
        person.memory.read_heartbeat_config.return_value = "5分ごと"
        person.memory.read_cron_config.return_value = ""
        person.set_on_lock_released = MagicMock()

        lm.register_person(person)
        jobs = lm.scheduler.get_jobs()
        hb_job = next(j for j in jobs if j.id == "bob_heartbeat")
        assert str(hb_job.trigger).find("*/30") != -1

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


# ── Command-type cron execution ───────────────────────────


class TestCommandTypeCron:
    """Test command-type cron execution (bash and tool)."""

    async def test_run_cron_command_bash_success(self):
        """Test successful bash command execution in cron."""
        from pathlib import Path
        from unittest.mock import patch, MagicMock
        from core.person import DigitalPerson
        from core.memory import MemoryManager

        # Create mock person
        person_dir = Path("/tmp/test_person")
        shared_dir = Path("/tmp/shared")
        person_dir.mkdir(parents=True, exist_ok=True)
        shared_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(MemoryManager, "read_model_config"):
            person = DigitalPerson(person_dir, shared_dir)

        # Mock append_cron_command_log
        person.memory.append_cron_command_log = MagicMock()

        # Execute command
        result = await person.run_cron_command(
            "test_task",
            command="echo 'Hello World'",
        )

        # Verify result
        assert result["exit_code"] == 0
        assert "Hello World" in result["stdout"]
        assert result["stderr"] == ""
        person.memory.append_cron_command_log.assert_called_once()

    async def test_run_cron_command_bash_failure(self):
        """Test bash command that returns non-zero exit code."""
        from pathlib import Path
        from unittest.mock import patch, MagicMock
        from core.person import DigitalPerson
        from core.memory import MemoryManager

        person_dir = Path("/tmp/test_person2")
        shared_dir = Path("/tmp/shared2")
        person_dir.mkdir(parents=True, exist_ok=True)
        shared_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(MemoryManager, "read_model_config"):
            person = DigitalPerson(person_dir, shared_dir)

        person.memory.append_cron_command_log = MagicMock()

        # Execute failing command
        result = await person.run_cron_command(
            "failing_task",
            command="exit 1",
        )

        # Verify non-zero exit code
        assert result["exit_code"] == 1
        person.memory.append_cron_command_log.assert_called_once()

    async def test_run_cron_command_tool(self):
        """Test internal tool execution in cron."""
        from pathlib import Path
        from unittest.mock import patch, MagicMock
        from core.person import DigitalPerson
        from core.memory import MemoryManager

        person_dir = Path("/tmp/test_person3")
        shared_dir = Path("/tmp/shared3")
        person_dir.mkdir(parents=True, exist_ok=True)
        shared_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(MemoryManager, "read_model_config"):
            person = DigitalPerson(person_dir, shared_dir)

        person.memory.append_cron_command_log = MagicMock()

        # Mock tool_handler.handle
        person.agent._tool_handler.handle = MagicMock(return_value="Tool executed successfully")

        # Execute tool
        result = await person.run_cron_command(
            "tool_task",
            tool="test_tool",
            args={"key": "value"},
        )

        # Verify result
        assert result["exit_code"] == 0
        assert "Tool executed successfully" in result["stdout"]
        person.agent._tool_handler.handle.assert_called_once_with(
            "test_tool",
            {"key": "value"},
        )
        person.memory.append_cron_command_log.assert_called_once()


# ── ReloadPersonSchedule ─────────────────────────────────


class TestReloadPersonSchedule:
    def test_reload_nonexistent_person(self):
        lm = LifecycleManager()
        result = lm.reload_person_schedule("nobody")
        assert "error" in result

    def test_reload_registered_person(self):
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "alice"
        person.memory.read_heartbeat_config.return_value = "9:00 - 22:00"
        person.memory.read_cron_config.return_value = ""
        person.set_on_lock_released = MagicMock()
        person.set_on_schedule_changed = MagicMock()

        lm.register_person(person)
        initial_jobs = [j.id for j in lm.scheduler.get_jobs() if j.id.startswith("alice_")]
        assert len(initial_jobs) >= 1

        # Change active hours only; interval stays 30
        person.memory.read_heartbeat_config.return_value = "8:00 - 23:00"
        result = lm.reload_person_schedule("alice")

        assert result["reloaded"] == "alice"
        assert result["removed"] >= 1
        assert len(result["new_jobs"]) >= 1
        # Verify interval is still 30 after reload
        hb_job = next(
            j for j in lm.scheduler.get_jobs() if j.id == "alice_heartbeat"
        )
        assert str(hb_job.trigger).find("*/30") != -1

    def test_reload_with_cron_tasks(self):
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "bob"
        person.memory.read_heartbeat_config.return_value = "30分ごと\n9:00 - 22:00"
        person.memory.read_cron_config.return_value = ""
        person.set_on_lock_released = MagicMock()
        person.set_on_schedule_changed = MagicMock()

        lm.register_person(person)

        # Add a cron task and reload
        person.memory.read_cron_config.return_value = """\
## ログチェック（毎日 10:00 JST）
type: llm
サーバーログを確認する。
"""
        result = lm.reload_person_schedule("bob")
        assert result["reloaded"] == "bob"
        # Should have heartbeat + cron job
        assert len(result["new_jobs"]) >= 2

    def test_register_person_wires_schedule_callback(self):
        lm = LifecycleManager()
        person = MagicMock()
        person.name = "alice"
        person.memory.read_heartbeat_config.return_value = ""
        person.memory.read_cron_config.return_value = ""
        person.set_on_lock_released = MagicMock()
        person.set_on_schedule_changed = MagicMock()

        lm.register_person(person)
        person.set_on_schedule_changed.assert_called_once_with(lm.reload_person_schedule)
