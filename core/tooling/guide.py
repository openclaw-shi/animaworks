from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


"""Dynamic tool guide generation for A1 (CLI) and A2 (schema) modes.

Replaces the static ``tools_guide.md`` template with dynamically generated
content derived from the same ``get_tool_schemas()`` functions used by A2
mode.  Both execution modes now share a single source of truth for tool
metadata.
"""

import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("animaworks.tool_guide")


def build_tools_guide(
    tool_registry: list[str],
    personal_tools: dict[str, str] | None = None,
) -> str:
    """Build a markdown CLI guide for allowed tools.

    Iterates over *tool_registry*, imports each module, and either:

    1. Calls ``get_cli_guide()`` if the module provides one, or
    2. Auto-generates from ``get_tool_schemas()`` (fallback).

    Args:
        tool_registry: Allowed tool names (e.g. ``["web_search", "image_gen"]``).
        personal_tools: Mapping of personal tool name → absolute file path.

    Returns:
        Markdown string suitable for system prompt injection.
        Empty string if no tools are allowed.
    """
    if not tool_registry and not personal_tools:
        return ""

    from core.tools import TOOL_MODULES
    from core.tools._base import auto_cli_guide

    parts: list[str] = [
        "## 外部ツール",
        "",
        "以下の外部ツールが `animaworks-tool` コマンド経由で使えます。",
        "Bashツールから実行してください。出力はJSON形式（`-j` オプション）を推奨します。",
        "",
    ]

    # Core tools
    for tool_name in sorted(tool_registry):
        if tool_name not in TOOL_MODULES:
            continue
        guide = _guide_from_module_path(tool_name, TOOL_MODULES[tool_name])
        if guide:
            parts.append(guide)
            parts.append("")

    # Personal tools
    if personal_tools:
        for tool_name in sorted(personal_tools):
            guide = _guide_from_file(tool_name, personal_tools[tool_name])
            if guide:
                parts.append(guide)
                parts.append("")

    parts.extend([
        "### 注意事項",
        "- 使えるツールは上記のみ（permissions.mdで許可されたもの）",
        "- APIキーが未設定のツールはエラーになる。エラー内容を確認して報告すること",
        "- 検索結果やメッセージ一覧は記憶に保存すべきか判断すること",
    ])

    return "\n".join(parts)


def load_tool_schemas(
    tool_registry: list[str],
    personal_tools: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Load structured schemas for A2 mode.

    Thin wrapper around ``tool_schemas.load_external_schemas()`` that also
    handles personal tool modules.

    Args:
        tool_registry: Allowed core tool names.
        personal_tools: Mapping of personal tool name → absolute file path.

    Returns:
        List of canonical-format tool schemas.
    """
    from core.tooling.schemas import load_external_schemas

    schemas = load_external_schemas(tool_registry)

    if personal_tools:
        for tool_name, file_path in personal_tools.items():
            try:
                mod = _import_file(tool_name, file_path)
                if not hasattr(mod, "get_tool_schemas"):
                    continue
                for s in mod.get_tool_schemas():
                    schemas.append({
                        "name": s["name"],
                        "description": s.get("description", ""),
                        "parameters": s.get(
                            "input_schema", s.get("parameters", {}),
                        ),
                    })
            except Exception:
                logger.debug(
                    "Failed to load personal tool schemas: %s",
                    tool_name, exc_info=True,
                )

    return schemas


# ── Helpers ───────────────────────────────────────────────────


def _guide_from_module_path(tool_name: str, module_path: str) -> str | None:
    """Generate a CLI guide from a package-importable module."""
    from core.tools._base import auto_cli_guide

    try:
        mod = importlib.import_module(module_path)
        return _extract_guide(tool_name, mod)
    except Exception:
        logger.debug("Failed to generate guide for %s", tool_name, exc_info=True)
        return None


def _guide_from_file(tool_name: str, file_path: str) -> str | None:
    """Generate a CLI guide from a file-based personal tool module."""
    from core.tools._base import auto_cli_guide

    try:
        mod = _import_file(tool_name, file_path)
        return _extract_guide(tool_name, mod)
    except Exception:
        logger.debug(
            "Failed to generate guide for personal tool %s",
            tool_name, exc_info=True,
        )
        return None


def _extract_guide(tool_name: str, mod: Any) -> str | None:
    """Extract CLI guide from a loaded module (hand-crafted or auto)."""
    from core.tools._base import auto_cli_guide

    if hasattr(mod, "get_cli_guide"):
        return mod.get_cli_guide()
    if hasattr(mod, "get_tool_schemas"):
        schemas = mod.get_tool_schemas()
        return auto_cli_guide(tool_name, schemas)
    return None


def _import_file(name: str, file_path: str) -> Any:
    """Import a Python module from an absolute file path."""
    spec = importlib.util.spec_from_file_location(
        f"animaworks_personal_tool_{name}", file_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod
