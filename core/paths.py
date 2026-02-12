"""Centralized path resolution for AnimaWorks.

All modules import directory paths from here instead of computing them ad-hoc.
Runtime data directory can be overridden via ANIMAWORKS_DATA_DIR environment variable.
"""

from __future__ import annotations

import os
from pathlib import Path

# Project root: where the code lives (immutable, git-tracked)
PROJECT_DIR = Path(__file__).resolve().parent.parent

# Templates shipped with the project
TEMPLATES_DIR = PROJECT_DIR / "templates"

# Default runtime data directory
_DEFAULT_DATA_DIR = Path.home() / ".animaworks"


def get_data_dir() -> Path:
    """Return the runtime data directory, respecting ANIMAWORKS_DATA_DIR env var."""
    env_val = os.environ.get("ANIMAWORKS_DATA_DIR")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return _DEFAULT_DATA_DIR


def get_persons_dir() -> Path:
    return get_data_dir() / "persons"


def get_shared_dir() -> Path:
    return get_data_dir() / "shared"


def get_company_dir() -> Path:
    return get_data_dir() / "company"


def get_tmp_dir() -> Path:
    return get_data_dir() / "tmp"
