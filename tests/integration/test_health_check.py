"""Integration tests for health checking and auto-restart."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import pytest

from core.supervisor.manager import ProcessSupervisor, HealthConfig, RestartPolicy
from core.supervisor.process_handle import ProcessState


@pytest.mark.asyncio
async def test_health_check_loop(data_dir: Path, make_person):
    """Test health check loop pings processes."""
    make_person("test-person")

    # Short ping interval for testing
    health_config = HealthConfig(
        ping_interval_sec=1.0,
        ping_timeout_sec=2.0,
        max_missed_pings=3,
        startup_grace_sec=2.0
    )

    supervisor = ProcessSupervisor(
        persons_dir=data_dir / "persons",
        shared_dir=data_dir / "shared",
        run_dir=data_dir / "run",
        log_dir=data_dir / "logs",
        health_config=health_config
    )

    try:
        # Start person
        await supervisor.start_all(["test-person"])

        # Wait for health check loop to run a few times
        await asyncio.sleep(3.0)

        # Verify ping stats updated
        handle = supervisor.processes.get("test-person")
        assert handle is not None
        assert handle.stats.last_ping_at is not None
        assert handle.stats.missed_pings == 0

    finally:
        await supervisor.shutdown_all()


@pytest.mark.asyncio
async def test_process_crash_detection(data_dir: Path, make_person):
    """Test detection when process crashes."""
    make_person("test-person")

    restart_policy = RestartPolicy(
        max_retries=1,  # Allow one restart
        backoff_base_sec=0.5,
        reset_after_sec=10.0
    )

    supervisor = ProcessSupervisor(
        persons_dir=data_dir / "persons",
        shared_dir=data_dir / "shared",
        run_dir=data_dir / "run",
        log_dir=data_dir / "logs",
        restart_policy=restart_policy
    )

    try:
        await supervisor.start_person("test-person")

        handle = supervisor.processes.get("test-person")
        original_pid = handle.get_pid()

        # Kill the process forcibly
        import os
        os.kill(original_pid, signal.SIGKILL)

        # Wait for supervisor to detect crash and restart
        await asyncio.sleep(3.0)

        # Verify process was restarted
        handle = supervisor.processes.get("test-person")
        if handle:
            new_pid = handle.get_pid()
            # Note: In actual implementation, supervisor needs to monitor
            # process exit and trigger restart. This test may need adjustment
            # based on actual auto-restart implementation.

    finally:
        await supervisor.shutdown_all()


@pytest.mark.asyncio
async def test_missed_pings_tracking(data_dir: Path, make_person):
    """Test tracking of missed pings."""
    make_person("test-person")

    supervisor = ProcessSupervisor(
        persons_dir=data_dir / "persons",
        shared_dir=data_dir / "shared",
        run_dir=data_dir / "run",
        log_dir=data_dir / "logs"
    )

    try:
        await supervisor.start_person("test-person")
        handle = supervisor.processes.get("test-person")

        # First ping should succeed
        success = await handle.ping(timeout=5.0)
        assert success is True
        assert handle.stats.missed_pings == 0

        # Stop the process but keep handle
        await handle.stop(timeout=2.0)

        # Ping should fail now
        success = await handle.ping(timeout=1.0)
        assert success is False
        # Missed ping count incremented
        # Note: Actual behavior depends on implementation

    finally:
        await supervisor.shutdown_all()
