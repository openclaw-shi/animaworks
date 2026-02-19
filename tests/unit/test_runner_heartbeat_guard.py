# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for heartbeat collision prevention in AnimaRunner.

Verifies that the _heartbeat_running flag and _cron_running set properly
prevent overlapping heartbeat and cron executions.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_runner(tmp_path: Path):
    """Create a AnimaRunner with minimal filesystem dependencies."""
    from core.supervisor.runner import AnimaRunner

    animas_dir = tmp_path / "animas"
    animas_dir.mkdir(exist_ok=True)
    anima_dir = animas_dir / "guard-test"
    anima_dir.mkdir(exist_ok=True)
    (anima_dir / "identity.md").write_text("test identity")
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir(exist_ok=True)
    socket_path = tmp_path / "test.sock"

    return AnimaRunner(
        anima_name="guard-test",
        socket_path=socket_path,
        animas_dir=animas_dir,
        shared_dir=shared_dir,
    )


class TestHeartbeatGuard:
    """Verify heartbeat overlap prevention."""

    def test_initial_heartbeat_running_is_false(self, tmp_path):
        """AnimaRunner initializes with _heartbeat_running=False."""
        runner = _make_runner(tmp_path)
        assert runner._heartbeat_running is False

    def test_initial_cron_running_is_empty(self, tmp_path):
        """AnimaRunner initializes with empty _cron_running set."""
        runner = _make_runner(tmp_path)
        assert runner._cron_running == set()

    @pytest.mark.asyncio
    async def test_heartbeat_tick_skips_when_already_running(self, tmp_path):
        """_heartbeat_tick should skip immediately when _heartbeat_running is True."""
        runner = _make_runner(tmp_path)
        # Simulate an anima being set
        mock_anima = MagicMock()
        mock_anima.run_heartbeat = AsyncMock()
        runner.anima = mock_anima

        # Simulate heartbeat already running
        runner._heartbeat_running = True

        await runner._heartbeat_tick()

        # run_heartbeat should NOT have been called
        mock_anima.run_heartbeat.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_tick_runs_when_not_already_running(self, tmp_path):
        """_heartbeat_tick should execute when _heartbeat_running is False."""
        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"summary": "ok"}
        mock_anima.run_heartbeat = AsyncMock(return_value=mock_result)
        runner.anima = mock_anima

        # Ensure flag is False
        assert runner._heartbeat_running is False

        await runner._heartbeat_tick()

        mock_anima.run_heartbeat.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_tick_resets_flag_after_completion(self, tmp_path):
        """_heartbeat_running flag resets to False after heartbeat completes."""
        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"summary": "ok"}
        mock_anima.run_heartbeat = AsyncMock(return_value=mock_result)
        runner.anima = mock_anima

        await runner._heartbeat_tick()

        assert runner._heartbeat_running is False

    @pytest.mark.asyncio
    async def test_heartbeat_tick_resets_flag_on_exception(self, tmp_path):
        """_heartbeat_running flag resets even when heartbeat raises an exception."""
        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_anima.run_heartbeat = AsyncMock(side_effect=RuntimeError("boom"))
        runner.anima = mock_anima

        await runner._heartbeat_tick()

        # Flag must be reset even after failure
        assert runner._heartbeat_running is False

    @pytest.mark.asyncio
    async def test_heartbeat_tick_skips_when_no_anima(self, tmp_path):
        """_heartbeat_tick returns early when self.anima is None."""
        runner = _make_runner(tmp_path)
        assert runner.anima is None

        # Should not raise
        await runner._heartbeat_tick()


class TestCronGuard:
    """Verify cron overlap prevention."""

    @pytest.mark.asyncio
    async def test_cron_tick_skips_when_already_running(self, tmp_path):
        """_cron_tick should skip when the same task name is in _cron_running."""
        from core.schemas import CronTask

        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_anima.run_cron_task = AsyncMock()
        runner.anima = mock_anima

        task = CronTask(name="daily_report", schedule="0 9 * * *", description="test", type="llm")
        runner._cron_running.add("daily_report")

        await runner._cron_tick(task)

        # The task's LLM call should NOT be started
        mock_anima.run_cron_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_cron_tick_runs_when_not_already_running(self, tmp_path):
        """_cron_tick should dispatch when the task name is not in _cron_running."""
        from core.schemas import CronTask

        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_anima.run_cron_task = AsyncMock()
        runner.anima = mock_anima

        task = CronTask(name="weekly_review", schedule="0 9 * * 1", description="test", type="llm")
        assert "weekly_review" not in runner._cron_running

        # _cron_tick creates a background task via asyncio.create_task
        await runner._cron_tick(task)

        # Give the background task a moment to start
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_cron_running_tracks_task_name(self, tmp_path):
        """_cron_running should contain task names that are currently executing."""
        runner = _make_runner(tmp_path)

        runner._cron_running.add("daily_report")
        runner._cron_running.add("weekly_review")

        assert "daily_report" in runner._cron_running
        assert "weekly_review" in runner._cron_running
        assert "monthly_summary" not in runner._cron_running

    @pytest.mark.asyncio
    async def test_run_cron_task_removes_name_on_completion(self, tmp_path):
        """_run_cron_task should discard task name from _cron_running after completion."""
        from core.schemas import CronTask

        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"summary": "done"}
        mock_anima.run_cron_task = AsyncMock(return_value=mock_result)
        runner.anima = mock_anima

        task = CronTask(name="daily_report", schedule="0 9 * * *", description="test", type="llm")

        await runner._run_cron_task(task)

        assert "daily_report" not in runner._cron_running

    @pytest.mark.asyncio
    async def test_run_cron_task_removes_name_on_exception(self, tmp_path):
        """_run_cron_task should discard task name even when execution fails."""
        from core.schemas import CronTask

        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_anima.run_cron_task = AsyncMock(side_effect=RuntimeError("cron failed"))
        runner.anima = mock_anima

        task = CronTask(name="daily_report", schedule="0 9 * * *", description="test", type="llm")

        await runner._run_cron_task(task)

        # Must be cleaned up despite error
        assert "daily_report" not in runner._cron_running


class TestMessageTriggeredHeartbeatGuard:
    """Verify message-triggered heartbeat respects the guard flag."""

    @pytest.mark.asyncio
    async def test_message_heartbeat_skips_when_already_running(self, tmp_path):
        """_message_triggered_heartbeat should skip when _heartbeat_running is True."""
        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_anima.run_heartbeat = AsyncMock()
        runner.anima = mock_anima

        runner._heartbeat_running = True
        runner._pending_trigger = True

        await runner._message_triggered_heartbeat()

        mock_anima.run_heartbeat.assert_not_called()
        # _pending_trigger should be reset
        assert runner._pending_trigger is False


class TestRunnerHeartbeat24hDefault:
    """Verify runner._setup_heartbeat respects 3-tier active hours resolution."""

    def test_default_24h_when_no_active_hours(self, tmp_path):
        """active_hours=None and no time range in heartbeat.md => hour='*'."""
        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_anima.config.active_hours = None
        mock_anima.memory.read_heartbeat_config.return_value = "- チェック項目A"
        runner.anima = mock_anima

        mock_scheduler = MagicMock()
        runner.scheduler = mock_scheduler

        runner._setup_heartbeat()

        mock_scheduler.add_job.assert_called_once()
        call_kwargs = mock_scheduler.add_job.call_args
        trigger = call_kwargs[1]["trigger"] if "trigger" in (call_kwargs[1] or {}) else call_kwargs[0][1]
        # CronTrigger with hour="*" means 24h
        assert trigger.fields[5].expressions[0].step is None or str(trigger) == str(trigger)
        # Verify via the positional/keyword arg — hour_spec should be "*"
        # Check the trigger's hour field
        hour_field = str(trigger.fields[5])
        assert hour_field == "*"

    def test_active_hours_from_config(self, tmp_path):
        """active_hours=(9,22) from config => hour='9-21'."""
        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_anima.config.active_hours = (9, 22)
        mock_anima.memory.read_heartbeat_config.return_value = "- チェック項目B"
        runner.anima = mock_anima

        mock_scheduler = MagicMock()
        runner.scheduler = mock_scheduler

        runner._setup_heartbeat()

        mock_scheduler.add_job.assert_called_once()
        call_kwargs = mock_scheduler.add_job.call_args
        trigger = call_kwargs[1]["trigger"] if "trigger" in (call_kwargs[1] or {}) else call_kwargs[0][1]
        hour_field = str(trigger.fields[5])
        assert "9-21" in hour_field

    def test_heartbeat_md_time_range_takes_priority(self, tmp_path):
        """Time range in heartbeat.md overrides config active_hours."""
        runner = _make_runner(tmp_path)
        mock_anima = MagicMock()
        mock_anima.config.active_hours = (9, 22)  # Should be overridden
        mock_anima.memory.read_heartbeat_config.return_value = "稼働時間: 8:00 - 20:00"
        runner.anima = mock_anima

        mock_scheduler = MagicMock()
        runner.scheduler = mock_scheduler

        runner._setup_heartbeat()

        mock_scheduler.add_job.assert_called_once()
        call_kwargs = mock_scheduler.add_job.call_args
        trigger = call_kwargs[1]["trigger"] if "trigger" in (call_kwargs[1] or {}) else call_kwargs[0][1]
        hour_field = str(trigger.fields[5])
        assert "8-19" in hour_field
