from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.

"""Authentication configuration manager."""

import json
import logging
import os
from pathlib import Path

from core.auth.models import AuthConfig
from core.paths import get_data_dir

logger = logging.getLogger("animaworks.auth")

_AUTH_FILENAME = "auth.json"


def get_auth_path() -> Path:
    """Return the path to the auth.json configuration file."""
    return get_data_dir() / _AUTH_FILENAME


def load_auth() -> AuthConfig:
    """Load auth configuration from disk, returning defaults if not found."""
    path = get_auth_path()
    if not path.exists():
        return AuthConfig()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return AuthConfig.model_validate(raw)


def save_auth(config: AuthConfig) -> None:
    """Atomically save auth configuration to disk with restrictive permissions."""
    path = get_auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        config.model_dump_json(indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)
    # Set restrictive permissions
    try:
        path.chmod(0o600)
    except OSError:
        pass
    logger.info("Saved auth config to %s", path)
