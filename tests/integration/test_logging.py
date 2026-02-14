"""Integration tests for person-specific logging."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from core.supervisor.manager import ProcessSupervisor


@pytest.mark.asyncio
async def test_person_log_file_created(data_dir: Path, make_person):
    """Test that person-specific log files are created."""
    make_person("test-person")

    supervisor = ProcessSupervisor(
        persons_dir=data_dir / "persons",
        shared_dir=data_dir / "shared",
        run_dir=data_dir / "run",
        log_dir=data_dir / "logs"
    )

    try:
        # Start person
        await supervisor.start_person("test-person")

        # Wait for log file to be created
        await asyncio.sleep(2.0)

        # Verify log directory exists
        person_log_dir = data_dir / "logs" / "persons" / "test-person"
        assert person_log_dir.exists()
        assert person_log_dir.is_dir()

        # Verify log file exists
        log_files = list(person_log_dir.glob("*.log"))
        assert len(log_files) > 0

        # Verify current.log symlink exists
        current_link = person_log_dir / "current.log"
        assert current_link.exists()

    finally:
        await supervisor.shutdown_all()


@pytest.mark.asyncio
async def test_person_log_contains_messages(data_dir: Path, make_person):
    """Test that person logs contain actual log messages."""
    make_person("test-person")

    supervisor = ProcessSupervisor(
        persons_dir=data_dir / "persons",
        shared_dir=data_dir / "shared",
        run_dir=data_dir / "run",
        log_dir=data_dir / "logs"
    )

    try:
        # Start person
        await supervisor.start_person("test-person")

        # Wait for initialization
        await asyncio.sleep(2.0)

        # Send a ping to generate log activity
        await supervisor.send_request("test-person", "ping", {})

        # Wait for log to be written
        await asyncio.sleep(1.0)

        # Read log file
        person_log_dir = data_dir / "logs" / "persons" / "test-person"
        current_link = person_log_dir / "current.log"

        if current_link.is_symlink():
            log_file = person_log_dir / current_link.readlink()
        else:
            # Fallback for non-symlink systems
            log_files = sorted(person_log_dir.glob("*.log"))
            log_file = log_files[0]

        log_content = log_file.read_text()

        # Verify log contains initialization messages
        assert "Initializing Person" in log_content or "Person process ready" in log_content

    finally:
        await supervisor.shutdown_all()


@pytest.mark.asyncio
async def test_multiple_person_logs_separated(data_dir: Path, make_person):
    """Test that multiple persons have separate log files."""
    make_person("alice")
    make_person("bob")

    supervisor = ProcessSupervisor(
        persons_dir=data_dir / "persons",
        shared_dir=data_dir / "shared",
        run_dir=data_dir / "run",
        log_dir=data_dir / "logs"
    )

    try:
        # Start both persons
        await supervisor.start_all(["alice", "bob"])

        # Wait for logs
        await asyncio.sleep(2.0)

        # Verify separate log directories
        alice_log_dir = data_dir / "logs" / "persons" / "alice"
        bob_log_dir = data_dir / "logs" / "persons" / "bob"

        assert alice_log_dir.exists()
        assert bob_log_dir.exists()

        # Verify separate log files
        alice_logs = list(alice_log_dir.glob("*.log"))
        bob_logs = list(bob_log_dir.glob("*.log"))

        assert len(alice_logs) > 0
        assert len(bob_logs) > 0

        # Verify they are different files
        alice_log_paths = {f.resolve() for f in alice_logs}
        bob_log_paths = {f.resolve() for f in bob_logs}

        assert alice_log_paths.isdisjoint(bob_log_paths)

    finally:
        await supervisor.shutdown_all()


@pytest.mark.asyncio
async def test_log_file_date_format(data_dir: Path, make_person):
    """Test that log files use correct date format (YYYYMMDD.log)."""
    make_person("test-person")

    supervisor = ProcessSupervisor(
        persons_dir=data_dir / "persons",
        shared_dir=data_dir / "shared",
        run_dir=data_dir / "run",
        log_dir=data_dir / "logs"
    )

    try:
        await supervisor.start_person("test-person")
        await asyncio.sleep(2.0)

        person_log_dir = data_dir / "logs" / "persons" / "test-person"
        log_files = list(person_log_dir.glob("*.log"))

        # Find dated log file (exclude current.log)
        dated_logs = [f for f in log_files if f.name != "current.log"]
        assert len(dated_logs) > 0

        # Verify filename format (YYYYMMDD.log)
        import re
        date_pattern = re.compile(r"^\d{8}\.log$")

        for log_file in dated_logs:
            assert date_pattern.match(log_file.name), f"Invalid log filename: {log_file.name}"

    finally:
        await supervisor.shutdown_all()
