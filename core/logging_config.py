# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.

"""Centralized logging configuration for AnimaWorks.

Provides:
- RequestIdFilter: contextvars-based request ID injection into all log records
- JsonFormatter: JSONL file output for machine parsing
- setup_logging(): one-call configuration for console + file handlers
"""

from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def set_request_id(request_id: str) -> None:
    """Set the current request ID (flows automatically through async calls)."""
    _request_id_var.set(request_id)


def get_request_id() -> str:
    """Get the current request ID."""
    return _request_id_var.get()


class RequestIdFilter(logging.Filter):
    """Inject request_id from contextvars into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()  # type: ignore[attr-defined]
        return True


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON (JSONL)."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    log_dir: Path | None = None,
    json_file: bool = True,
) -> None:
    """Configure logging for the entire AnimaWorks process.

    Args:
        level: Root log level (DEBUG, INFO, WARNING, etc.).
        log_dir: Directory for log files. If None, file logging is disabled.
        json_file: Whether to use JSON format for the file handler.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers (replaces basicConfig)
    root.handlers.clear()

    req_filter = RequestIdFilter()

    # Console handler: human-readable
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    console.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    console.addFilter(req_filter)
    root.addHandler(console)

    # File handler: rotated, optionally JSON
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "animaworks.log"
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        if json_file:
            file_handler.setFormatter(JsonFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
                )
            )
        file_handler.addFilter(req_filter)
        root.addHandler(file_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


# ── Person-specific Logging ────────────────────────────────────────────


class PersonNameFilter(logging.Filter):
    """Inject person name into log records."""

    def __init__(self, person_name: str):
        super().__init__()
        self.person_name = person_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.person_name = self.person_name  # type: ignore[attr-defined]
        return True


def setup_person_logging(
    person_name: str,
    log_dir: Path,
    level: str = "INFO",
    also_to_console: bool = True
) -> None:
    """Configure person-specific logging with daily rotation.

    Creates a dedicated log directory for the person with:
    - Daily log rotation (YYYYMMDD.log format)
    - 30-day retention
    - current.log symlink to the current log file
    - Optional console output

    Args:
        person_name: Name of the person (used for log directory and prefix)
        log_dir: Base log directory (e.g., ~/.animaworks/logs)
        level: Log level (DEBUG, INFO, WARNING, etc.)
        also_to_console: Whether to also log to console

    Directory structure created:
        {log_dir}/persons/{person_name}/
        ├── current.log -> 20260214.log
        ├── 20260214.log
        ├── 20260213.log
        └── ...
    """
    # Create person log directory
    person_log_dir = log_dir / "persons" / person_name
    person_log_dir.mkdir(parents=True, exist_ok=True)

    # Main log file with daily rotation
    log_file = person_log_dir / f"{datetime.now().strftime('%Y%m%d')}.log"

    # Setup root logger
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    # Create person name filter
    person_filter = PersonNameFilter(person_name)

    # File handler with timed rotation
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=30,  # Keep 30 days
        encoding="utf-8",
        utc=False
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    file_handler.addFilter(person_filter)
    file_handler.suffix = "%Y%m%d.log"  # Match filename format
    root.addHandler(file_handler)

    # Create/update current.log symlink
    current_link = person_log_dir / "current.log"
    if current_link.exists() or current_link.is_symlink():
        current_link.unlink()
    try:
        current_link.symlink_to(log_file.name)
    except OSError:
        # On Windows, symlinks may require admin privileges
        # Fall back to copying the path as a text file reference
        current_link.write_text(str(log_file.name))

    # Optional console handler
    if also_to_console:
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        console.setFormatter(
            logging.Formatter(
                fmt=f"[{person_name}] %(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S"
            )
        )
        console.addFilter(person_filter)
        root.addHandler(console)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info(f"Person logging configured: {person_name} -> {log_file}")