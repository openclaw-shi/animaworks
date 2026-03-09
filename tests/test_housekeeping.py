from __future__ import annotations

# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0

"""Tests for core.memory.housekeeping and related modules."""

import asyncio
import os
import time
from datetime import timedelta
from pathlib import Path

from core.time_utils import today_local
from unittest.mock import patch

import pytest


# ── HousekeepingConfig tests ────────────────────────────────────


class TestHousekeepingConfig:
    """Test HousekeepingConfig defaults and customization."""

    def test_default_values(self):
        from core.config.models import HousekeepingConfig

        cfg = HousekeepingConfig()
        assert cfg.enabled is True
        assert cfg.run_time == "05:30"
        assert cfg.prompt_log_retention_days == 3
        assert cfg.daemon_log_max_size_mb == 100
        assert cfg.daemon_log_keep_generations == 5
        assert cfg.frontend_log_backup_count == 7
        assert cfg.dm_log_archive_retention_days == 30
        assert cfg.cron_log_retention_days == 30
        assert cfg.shortterm_retention_days == 7

    def test_custom_values(self):
        from core.config.models import HousekeepingConfig

        cfg = HousekeepingConfig(
            enabled=False,
            run_time="03:00",
            prompt_log_retention_days=7,
            daemon_log_max_size_mb=200,
            daemon_log_keep_generations=3,
            frontend_log_backup_count=14,
            dm_log_archive_retention_days=60,
            cron_log_retention_days=14,
            shortterm_retention_days=14,
        )
        assert cfg.enabled is False
        assert cfg.run_time == "03:00"
        assert cfg.prompt_log_retention_days == 7
        assert cfg.daemon_log_max_size_mb == 200

    def test_config_has_housekeeping_field(self):
        from core.config.models import AnimaWorksConfig

        cfg = AnimaWorksConfig()
        assert hasattr(cfg, "housekeeping")
        assert cfg.housekeeping.enabled is True

    def test_config_json_round_trip(self):
        from core.config.models import AnimaWorksConfig

        cfg = AnimaWorksConfig()
        data = cfg.model_dump()
        assert "housekeeping" in data
        assert data["housekeeping"]["enabled"] is True
        assert data["housekeeping"]["run_time"] == "05:30"

        restored = AnimaWorksConfig(**data)
        assert restored.housekeeping.prompt_log_retention_days == 3


# ── rotate_all_prompt_logs tests ────────────────────────────────


class TestRotateAllPromptLogs:
    """Test the rotate_all_prompt_logs function."""

    def test_deletes_old_logs(self, tmp_path: Path):
        from core._agent_prompt_log import rotate_all_prompt_logs

        anima_dir = tmp_path / "alice"
        log_dir = anima_dir / "prompt_logs"
        log_dir.mkdir(parents=True)

        old_date = (today_local() - timedelta(days=5)).isoformat()
        today = today_local().isoformat()
        (log_dir / f"{old_date}.jsonl").write_text("{}\n")
        (log_dir / f"{today}.jsonl").write_text("{}\n")

        result = rotate_all_prompt_logs(tmp_path, retention_days=3)
        assert "alice" in result
        assert result["alice"] == 1
        assert not (log_dir / f"{old_date}.jsonl").exists()
        assert (log_dir / f"{today}.jsonl").exists()

    def test_skips_non_directories(self, tmp_path: Path):
        from core._agent_prompt_log import rotate_all_prompt_logs

        (tmp_path / "not_a_dir.txt").write_text("hello")
        result = rotate_all_prompt_logs(tmp_path, retention_days=3)
        assert result == {}

    def test_skips_anima_without_prompt_logs(self, tmp_path: Path):
        from core._agent_prompt_log import rotate_all_prompt_logs

        (tmp_path / "bob").mkdir()
        result = rotate_all_prompt_logs(tmp_path, retention_days=3)
        assert result == {}

    def test_no_old_files(self, tmp_path: Path):
        from core._agent_prompt_log import rotate_all_prompt_logs

        anima_dir = tmp_path / "charlie"
        log_dir = anima_dir / "prompt_logs"
        log_dir.mkdir(parents=True)
        today = today_local().isoformat()
        (log_dir / f"{today}.jsonl").write_text("{}\n")

        result = rotate_all_prompt_logs(tmp_path, retention_days=3)
        assert result == {}

    def test_multiple_animas(self, tmp_path: Path):
        from core._agent_prompt_log import rotate_all_prompt_logs

        old_date = (today_local() - timedelta(days=10)).isoformat()

        for name in ("a1", "a2"):
            d = tmp_path / name / "prompt_logs"
            d.mkdir(parents=True)
            (d / f"{old_date}.jsonl").write_text("{}\n")

        result = rotate_all_prompt_logs(tmp_path, retention_days=3)
        assert len(result) == 2
        assert result["a1"] == 1
        assert result["a2"] == 1


# ── _rotate_daemon_log tests ───────────────────────────────────


class TestRotateDaemonLog:
    """Test daemon log rotation."""

    def test_skips_when_file_not_found(self, tmp_path: Path):
        from core.memory.housekeeping import _rotate_daemon_log

        result = _rotate_daemon_log(tmp_path / "nonexistent.log", 100, 5)
        assert result["skipped"] is True
        assert result["reason"] == "file_not_found"

    def test_skips_when_under_size(self, tmp_path: Path):
        from core.memory.housekeeping import _rotate_daemon_log

        log = tmp_path / "server-daemon.log"
        log.write_text("small content")
        result = _rotate_daemon_log(log, 100, 5)
        assert result["skipped"] is True

    def test_rotates_when_over_size(self, tmp_path: Path):
        from core.memory.housekeeping import _rotate_daemon_log

        log = tmp_path / "server-daemon.log"
        log.write_bytes(b"x" * (2 * 1024 * 1024))  # 2MB

        result = _rotate_daemon_log(log, max_size_mb=1, keep_generations=3)
        assert result["rotated"] is True
        assert not log.exists()  # original renamed
        assert (tmp_path / "server-daemon.log.1").exists()

    def test_shifts_existing_generations(self, tmp_path: Path):
        from core.memory.housekeeping import _rotate_daemon_log

        log = tmp_path / "server-daemon.log"
        log.write_bytes(b"x" * (2 * 1024 * 1024))
        (tmp_path / "server-daemon.log.1").write_text("gen1")
        (tmp_path / "server-daemon.log.2").write_text("gen2")

        result = _rotate_daemon_log(log, max_size_mb=1, keep_generations=3)
        assert result["rotated"] is True
        assert (tmp_path / "server-daemon.log.1").exists()
        assert (tmp_path / "server-daemon.log.2").read_text() == "gen1"
        assert (tmp_path / "server-daemon.log.3").read_text() == "gen2"

    def test_deletes_over_limit_generations(self, tmp_path: Path):
        from core.memory.housekeeping import _rotate_daemon_log

        log = tmp_path / "server-daemon.log"
        log.write_bytes(b"x" * (2 * 1024 * 1024))
        (tmp_path / "server-daemon.log.1").write_text("gen1")
        (tmp_path / "server-daemon.log.2").write_text("gen2")

        result = _rotate_daemon_log(log, max_size_mb=1, keep_generations=2)
        assert result["rotated"] is True
        assert not (tmp_path / "server-daemon.log.3").exists()


# ── _cleanup_dm_archives tests ─────────────────────────────────


class TestCleanupDmArchives:
    """Test DM archive cleanup."""

    def test_skips_when_dir_not_found(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_dm_archives

        result = _cleanup_dm_archives(tmp_path / "nonexistent", 30)
        assert result["skipped"] is True

    def test_deletes_old_archives(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_dm_archives

        old_archive = tmp_path / "alice-bob.20260101.archive.jsonl"
        old_archive.write_text("{}\n")
        old_time = time.time() - (60 * 86400)  # 60 days ago
        os.utime(old_archive, (old_time, old_time))

        recent_archive = tmp_path / "alice-charlie.20260304.archive.jsonl"
        recent_archive.write_text("{}\n")

        result = _cleanup_dm_archives(tmp_path, retention_days=30)
        assert result["deleted_files"] == 1
        assert not old_archive.exists()
        assert recent_archive.exists()

    def test_ignores_non_archive_files(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_dm_archives

        normal = tmp_path / "alice-bob.jsonl"
        normal.write_text("{}\n")
        old_time = time.time() - (60 * 86400)
        os.utime(normal, (old_time, old_time))

        result = _cleanup_dm_archives(tmp_path, retention_days=30)
        assert result["deleted_files"] == 0
        assert normal.exists()


# ── _cleanup_cron_logs tests ───────────────────────────────────


class TestCleanupCronLogs:
    """Test cron log cleanup."""

    def test_skips_when_dir_not_found(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_cron_logs

        result = _cleanup_cron_logs(tmp_path / "nonexistent", 30)
        assert result["skipped"] is True

    def test_deletes_old_cron_logs(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_cron_logs

        cron_dir = tmp_path / "alice" / "state" / "cron_logs"
        cron_dir.mkdir(parents=True)

        old_date = (today_local() - timedelta(days=40)).isoformat()
        today = today_local().isoformat()
        (cron_dir / f"{old_date}.jsonl").write_text("{}\n")
        (cron_dir / f"{today}.jsonl").write_text("{}\n")

        result = _cleanup_cron_logs(tmp_path, retention_days=30)
        assert result["deleted_files"] == 1
        assert not (cron_dir / f"{old_date}.jsonl").exists()
        assert (cron_dir / f"{today}.jsonl").exists()

    def test_skips_anima_without_cron_logs(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_cron_logs

        (tmp_path / "bob").mkdir()
        result = _cleanup_cron_logs(tmp_path, retention_days=30)
        assert result["deleted_files"] == 0


# ── _cleanup_shortterm tests ───────────────────────────────────


class TestCleanupShortterm:
    """Test shortterm cleanup."""

    def test_skips_when_dir_not_found(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_shortterm

        result = _cleanup_shortterm(tmp_path / "nonexistent", 7)
        assert result["skipped"] is True

    def test_deletes_old_session_files(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_shortterm

        chat_dir = tmp_path / "alice" / "shortterm" / "chat"
        chat_dir.mkdir(parents=True)

        old_file = chat_dir / "2026-01-01_session.json"
        old_file.write_text("{}")
        old_time = time.time() - (14 * 86400)  # 14 days ago
        os.utime(old_file, (old_time, old_time))

        recent_file = chat_dir / "2026-03-04_session.json"
        recent_file.write_text("{}")

        result = _cleanup_shortterm(tmp_path, retention_days=7)
        assert result["deleted_files"] == 1
        assert not old_file.exists()
        assert recent_file.exists()

    def test_preserves_current_session_files(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_shortterm

        chat_dir = tmp_path / "alice" / "shortterm" / "chat"
        chat_dir.mkdir(parents=True)

        protected = chat_dir / "current_session_chat.json"
        protected.write_text("{}")
        old_time = time.time() - (30 * 86400)
        os.utime(protected, (old_time, old_time))

        result = _cleanup_shortterm(tmp_path, retention_days=7)
        assert result["deleted_files"] == 0
        assert protected.exists()

    def test_preserves_streaming_journal_files(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_shortterm

        hb_dir = tmp_path / "alice" / "shortterm" / "heartbeat"
        hb_dir.mkdir(parents=True)

        protected = hb_dir / "streaming_journal_heartbeat.jsonl"
        protected.write_text("{}")
        old_time = time.time() - (30 * 86400)
        os.utime(protected, (old_time, old_time))

        result = _cleanup_shortterm(tmp_path, retention_days=7)
        assert result["deleted_files"] == 0
        assert protected.exists()

    def test_cleans_both_chat_and_heartbeat(self, tmp_path: Path):
        from core.memory.housekeeping import _cleanup_shortterm

        old_time = time.time() - (14 * 86400)
        for sub in ("chat", "heartbeat"):
            d = tmp_path / "alice" / "shortterm" / sub
            d.mkdir(parents=True)
            f = d / "old_session.json"
            f.write_text("{}")
            os.utime(f, (old_time, old_time))

        result = _cleanup_shortterm(tmp_path, retention_days=7)
        assert result["deleted_files"] == 2


# ── run_housekeeping integration test ──────────────────────────


class TestRunHousekeeping:
    """Integration test for the run_housekeeping orchestrator."""

    @pytest.mark.asyncio
    async def test_runs_all_tasks(self, tmp_path: Path):
        data_dir = tmp_path
        animas_dir = data_dir / "animas"

        # Set up prompt_logs
        alice_logs = animas_dir / "alice" / "prompt_logs"
        alice_logs.mkdir(parents=True)
        old_date = (today_local() - timedelta(days=5)).isoformat()
        (alice_logs / f"{old_date}.jsonl").write_text("{}\n")

        # Set up cron_logs
        cron_dir = animas_dir / "alice" / "state" / "cron_logs"
        cron_dir.mkdir(parents=True)
        old_cron = (today_local() - timedelta(days=40)).isoformat()
        (cron_dir / f"{old_cron}.jsonl").write_text("{}\n")

        # Set up shortterm
        chat_dir = animas_dir / "alice" / "shortterm" / "chat"
        chat_dir.mkdir(parents=True)
        old_st = chat_dir / "old_session.json"
        old_st.write_text("{}")
        old_time = time.time() - (14 * 86400)
        os.utime(old_st, (old_time, old_time))

        # Set up dm_logs dir (empty for this test)
        (data_dir / "shared" / "dm_logs").mkdir(parents=True)

        # Set up logs dir (no daemon log for this test)
        (data_dir / "logs").mkdir(parents=True)

        from core.memory.housekeeping import run_housekeeping

        results = await run_housekeeping(
            data_dir,
            prompt_log_retention_days=3,
            cron_log_retention_days=30,
            shortterm_retention_days=7,
        )

        assert "prompt_logs" in results
        assert results["prompt_logs"]["deleted_files"] == 1
        assert "cron_logs" in results
        assert results["cron_logs"]["deleted_files"] == 1
        assert "shortterm" in results
        assert results["shortterm"]["deleted_files"] == 1
        assert "daemon_log" in results
        assert results["daemon_log"]["skipped"] is True
        assert "dm_archives" in results

    @pytest.mark.asyncio
    async def test_handles_missing_dirs_gracefully(self, tmp_path: Path):
        from core.memory.housekeeping import run_housekeeping

        results = await run_housekeeping(tmp_path)

        assert "prompt_logs" in results
        assert "daemon_log" in results
        assert "dm_archives" in results
        assert "cron_logs" in results
        assert "shortterm" in results
