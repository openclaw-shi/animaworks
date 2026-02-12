"""First-launch initialization: copy templates to runtime data directory."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from core.paths import TEMPLATES_DIR, get_data_dir

logger = logging.getLogger("animaworks.init")


def ensure_runtime_dir() -> Path:
    """Ensure the runtime data directory exists, seeding from templates if needed.

    Returns the runtime data directory path.
    """
    data_dir = get_data_dir()

    if data_dir.exists():
        logger.debug("Runtime directory already exists: %s", data_dir)
        return data_dir

    logger.info("First launch: initializing runtime directory at %s", data_dir)

    if not TEMPLATES_DIR.exists():
        raise FileNotFoundError(
            f"Templates directory not found: {TEMPLATES_DIR}. "
            "Is the project installed correctly?"
        )

    # Copy templates tree: templates/persons/ -> data_dir/persons/, etc.
    data_dir.mkdir(parents=True, exist_ok=True)
    for item in TEMPLATES_DIR.iterdir():
        target = data_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)

    # Create runtime-only directories that have no template
    (data_dir / "shared" / "inbox").mkdir(parents=True, exist_ok=True)
    (data_dir / "tmp" / "attachments").mkdir(parents=True, exist_ok=True)

    logger.info("Runtime directory initialized: %s", data_dir)
    return data_dir
