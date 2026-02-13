from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


"""Canonical tool schema definitions and format converters.

All tool schemas are defined once in a provider-neutral format and converted
to Anthropic or LiteLLM/OpenAI formats on demand.  This eliminates the
duplicate definitions that previously lived in ``_build_a2_tools()`` and
``_build_anthropic_tools()``.
"""

import logging
from typing import Any

logger = logging.getLogger("animaworks.tool_schemas")

# ── Canonical definitions ────────────────────────────────────
#
# Format: {"name", "description", "parameters"} where ``parameters`` is a
# standard JSON Schema object.  This is convertible to both Anthropic
# (``input_schema``) and OpenAI/LiteLLM (``function.parameters``) formats.

MEMORY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_memory",
        "description": (
            "Search the person's long-term memory "
            "(knowledge, episodes, procedures) by keyword."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword"},
                "scope": {
                    "type": "string",
                    "enum": ["knowledge", "episodes", "procedures", "all"],
                    "description": "Memory category to search",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_memory_file",
        "description": "Read a file from the person's memory directory by relative path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within person dir",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_memory_file",
        "description": "Write or append to a file in the person's memory directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["overwrite", "append"]},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "send_message",
        "description": "Send a message to another person.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient person name"},
                "content": {"type": "string", "description": "Message content"},
                "reply_to": {"type": "string", "description": "Message ID to reply to"},
                "thread_id": {"type": "string", "description": "Thread ID"},
            },
            "required": ["to", "content"],
        },
    },
]

FILE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read an arbitrary file (subject to permissions).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file (subject to permissions).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace a specific string in a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "old_string": {"type": "string", "description": "Text to find"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "execute_command",
        "description": "Execute a shell command (subject to permissions allow-list).",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30)",
                },
            },
            "required": ["command"],
        },
    },
]

DELEGATE_TOOL: dict[str, Any] = {
    "name": "delegate_task",
    "description": "Delegate a task to a subordinate person and wait for the result.",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Subordinate person name"},
            "task": {"type": "string", "description": "Task instruction"},
            "context": {
                "type": "string",
                "description": "Background context (optional)",
            },
        },
        "required": ["to", "task"],
    },
}


# ── Format converters ────────────────────────────────────────


def to_anthropic_format(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert canonical schemas to Anthropic API format (``input_schema``)."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in tools
    ]


def to_litellm_format(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert canonical schemas to LiteLLM/OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in tools
    ]


# ── Builder helpers ──────────────────────────────────────────


def build_tool_list(
    *,
    include_file_tools: bool = False,
    include_delegate: bool = False,
    external_schemas: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Assemble a tool list from canonical definitions.

    Args:
        include_file_tools: Include file/command operation tools (for A2 mode).
        include_delegate: Include the delegate_task tool (for commanders).
        external_schemas: Additional tool schemas in canonical format.

    Returns:
        Combined list in canonical format.
    """
    tools: list[dict[str, Any]] = list(MEMORY_TOOLS)
    if include_file_tools:
        tools.extend(FILE_TOOLS)
    if include_delegate:
        tools.append(DELEGATE_TOOL)
    if external_schemas:
        tools.extend(external_schemas)
    return tools


def load_external_schemas(tool_registry: list[str]) -> list[dict[str, Any]]:
    """Load schemas from external tool modules, normalised to canonical format.

    External modules export Anthropic format (``input_schema``); this function
    converts them to the canonical format (``parameters``) used internally.
    """
    if not tool_registry:
        return []

    import importlib

    from core.tools import TOOL_MODULES

    schemas: list[dict[str, Any]] = []
    for tool_name in tool_registry:
        if tool_name not in TOOL_MODULES:
            continue
        try:
            mod = importlib.import_module(TOOL_MODULES[tool_name])
            if not hasattr(mod, "get_tool_schemas"):
                continue
            for s in mod.get_tool_schemas():
                schemas.append({
                    "name": s["name"],
                    "description": s.get("description", ""),
                    "parameters": s.get("input_schema", s.get("parameters", {})),
                })
        except Exception:
            logger.debug("Failed to load schemas for %s", tool_name, exc_info=True)
    return schemas