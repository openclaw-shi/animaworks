# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.

"""Migrate legacy config.md files to unified config.json."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("animaworks.config_migrate")


def _parse_config_md(path: Path) -> dict[str, str]:
    """Parse a legacy config.md file and return key-value pairs."""
    raw = path.read_text(encoding="utf-8")
    # Ignore 備考/設定例 sections
    for marker in ("## 備考", "### 設定例"):
        idx = raw.find(marker)
        if idx != -1:
            raw = raw[:idx]

    result = {}
    for m in re.finditer(r"^-\s*(\w+)\s*:\s*(.+)$", raw, re.MULTILINE):
        result[m.group(1).strip()] = m.group(2).strip()
    return result


def _env_name_to_credential_name(env_name: str) -> str:
    """Derive a credential name from an env var name.

    ANTHROPIC_API_KEY -> anthropic
    ANTHROPIC_API_KEY_SAKURA -> anthropic_sakura
    OLLAMA_API_KEY -> ollama
    """
    name = env_name.lower()
    # Remove _api_key suffix/infix
    name = re.sub(r"_api_key$", "", name)
    name = re.sub(r"_api_key_", "_", name)
    return name or "default"


def migrate_to_config_json(data_dir: Path) -> None:
    """Build config.json from existing config.md files and environment variables.

    Scans persons_dir for config.md files, parses them, collects credentials,
    and writes a unified config.json.
    """
    from core.config.models import (
        AnimaWorksConfig,
        CredentialConfig,
        PersonModelConfig,
        save_config,
    )

    persons_dir = data_dir / "persons"
    config = AnimaWorksConfig()

    if not persons_dir.exists():
        save_config(config, data_dir / "config.json")
        return

    seen_credentials: dict[str, CredentialConfig] = {}

    for person_dir in sorted(persons_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        config_md = person_dir / "config.md"
        if not config_md.exists():
            continue

        logger.info("Migrating config.md for person: %s", person_dir.name)
        parsed = _parse_config_md(config_md)

        # Determine credential
        api_key_env = parsed.get("api_key_env", "ANTHROPIC_API_KEY")
        base_url = parsed.get("api_base_url", "")
        cred_name = _env_name_to_credential_name(api_key_env)

        if cred_name not in seen_credentials:
            api_key_value = os.environ.get(api_key_env, "")
            seen_credentials[cred_name] = CredentialConfig(
                api_key=api_key_value,
                base_url=base_url or None,
            )

        # Build person config (only override non-default values)
        person_cfg = PersonModelConfig(
            model=parsed.get("model") or None,
            fallback_model=parsed.get("fallback_model") or None,
            max_tokens=int(parsed["max_tokens"]) if "max_tokens" in parsed else None,
            max_turns=int(parsed["max_turns"]) if "max_turns" in parsed else None,
            credential=cred_name,
        )
        config.persons[person_dir.name] = person_cfg

    config.credentials = seen_credentials

    # Ensure at least an "anthropic" credential exists
    if "anthropic" not in config.credentials:
        config.credentials["anthropic"] = CredentialConfig(
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )

    save_config(config, data_dir / "config.json")
    logger.info(
        "Migration complete: %d persons, %d credentials -> %s",
        len(config.persons),
        len(config.credentials),
        data_dir / "config.json",
    )