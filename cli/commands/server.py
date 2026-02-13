from __future__ import annotations

import argparse
import atexit
import logging
import os
import signal
import sys
import time
from pathlib import Path

logger = logging.getLogger("animaworks")


# ── PID helpers ───────────────────────────────────────────


def _get_pid_file() -> Path:
    """Return the path to the server PID file."""
    from core.paths import get_data_dir

    return get_data_dir() / "server.pid"


def _write_pid_file() -> None:
    """Write the current process PID to the PID file."""
    pid_file = _get_pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    logger.info("PID file written: %s (pid=%d)", pid_file, os.getpid())


def _remove_pid_file() -> None:
    """Remove the PID file if it exists."""
    pid_file = _get_pid_file()
    try:
        pid_file.unlink(missing_ok=True)
        logger.debug("PID file removed: %s", pid_file)
    except OSError as exc:
        logger.warning("Failed to remove PID file %s: %s", pid_file, exc)


def _read_pid() -> int | None:
    """Read and validate the PID from the PID file.

    Returns the PID if the file exists and contains a valid integer,
    or None if the file is missing or contains invalid data.
    """
    pid_file = _get_pid_file()
    if not pid_file.exists():
        return None
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
        return int(text)
    except (ValueError, OSError) as exc:
        logger.warning("Invalid PID file %s: %s", pid_file, exc)
        return None


def _is_process_alive(pid: int) -> bool:
    """Check whether a process with the given PID is currently running."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stop_server(timeout: int = 10) -> bool:
    """Send SIGTERM to the running server and wait for it to exit.

    Args:
        timeout: Maximum seconds to wait before reporting failure.

    Returns:
        True if the server was stopped (or was not running), False if
        it failed to stop within the timeout.
    """
    pid = _read_pid()
    if pid is None:
        print("No PID file found. Server is not running.")
        return True

    if not _is_process_alive(pid):
        print(f"Stale PID file (pid={pid}). Server is not running. Cleaning up.")
        _remove_pid_file()
        return True

    print(f"Stopping server (pid={pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print("Server already exited.")
        _remove_pid_file()
        return True
    except PermissionError:
        print(f"Error: Permission denied sending signal to pid={pid}.")
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_process_alive(pid):
            print("Server stopped.")
            _remove_pid_file()
            return True
        time.sleep(0.2)

    print(f"Error: Server (pid={pid}) did not stop within {timeout}s.")
    return False


# ── Server commands ───────────────────────────────────────


def cmd_start(args: argparse.Namespace) -> None:
    """Start the AnimaWorks server."""
    import uvicorn

    from core.init import ensure_runtime_dir
    from core.paths import get_persons_dir, get_shared_dir
    from server.app import create_app

    existing_pid = _read_pid()
    if existing_pid is not None and _is_process_alive(existing_pid):
        print(f"Error: Server is already running (pid={existing_pid}).")
        print("Use 'animaworks stop' first, or 'animaworks restart'.")
        sys.exit(1)
    elif existing_pid is not None:
        logger.info("Stale PID file found (pid=%d). Cleaning up.", existing_pid)
        _remove_pid_file()

    ensure_runtime_dir()
    _write_pid_file()
    atexit.register(_remove_pid_file)

    try:
        app = create_app(get_persons_dir(), get_shared_dir())
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        _remove_pid_file()


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the server (alias for 'start')."""
    cmd_start(args)


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop the running AnimaWorks server."""
    if not _stop_server():
        sys.exit(1)


def _clear_pycache() -> int:
    """Remove all __pycache__ directories under the project root.

    Returns the number of directories removed.
    """
    import shutil

    project_root = Path(__file__).resolve().parent.parent.parent
    count = 0
    for cache_dir in project_root.rglob("__pycache__"):
        try:
            shutil.rmtree(cache_dir)
            count += 1
        except OSError as exc:
            logger.warning("Failed to remove %s: %s", cache_dir, exc)
    return count


def cmd_restart(args: argparse.Namespace) -> None:
    """Restart the AnimaWorks server (stop then start)."""
    if not _stop_server():
        print("Error: Cannot restart — failed to stop the running server.")
        sys.exit(1)
    removed = _clear_pycache()
    if removed:
        print(f"Cleared {removed} __pycache__ directories.")
    time.sleep(0.5)
    cmd_start(args)


# ── Deprecated modes ──────────────────────────────────────


def cmd_gateway(args: argparse.Namespace) -> None:
    print("Error: 'gateway' mode has been deprecated. Use 'animaworks start' instead.")
    sys.exit(1)


def cmd_worker(args: argparse.Namespace) -> None:
    print("Error: 'worker' mode has been deprecated. Use 'animaworks start' instead.")
    sys.exit(1)
