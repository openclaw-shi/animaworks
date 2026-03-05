from __future__ import annotations

# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0

"""Shared permission parser for external tool access control.

Both MCP server (``core.mcp.server``) and AgentCore executor
(``core._agent_executor``) use :func:`parse_permitted_tools` to resolve
which external tools an Anima is allowed to invoke, keeping the logic
in a single authoritative location.
"""

import re

# ── Regex patterns ────────────────────────────────────────

_PERMISSION_ALLOW_RE = re.compile(
    r"[-*]?\s*(\w+)\s*:\s*(OK|yes|enabled|true|全権限|読み取り.*)\s*$",
    re.IGNORECASE,
)
_PERMISSION_ALL_RE = re.compile(
    r"[-*]?\s*all\s*:\s*(OK|yes|enabled|true)\s*$",
    re.IGNORECASE,
)
_PERMISSION_DENY_RE = re.compile(
    r"[-*]?\s*(\w+)\s*:\s*(no|deny|disabled|false)\s*$",
    re.IGNORECASE,
)


# ── Public API ────────────────────────────────────────────


def parse_permitted_tools(text: str) -> set[str]:
    """Parse permissions.md text and return permitted tool module names.

    Strategy:
      1. No ``外部ツール`` / ``External Tools`` section present → ALL tools (default-all)
      2. ``- all: yes`` found → ALL tools minus any deny entries
      3. Individual ``- tool: yes`` entries → whitelist mode (backward compat)
      4. Section present but no matching entries → ALL tools

    Returns:
        Set of permitted category names (keys from ``core.tools.TOOL_MODULES``).
    """
    from core.tools import TOOL_MODULES

    all_tools = set(TOOL_MODULES.keys())

    if "外部ツール" not in text and "External Tools" not in text:
        return all_tools

    has_all_yes = False
    allowed: list[str] = []
    denied: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if _PERMISSION_ALL_RE.match(stripped):
            has_all_yes = True
            continue
        m_deny = _PERMISSION_DENY_RE.match(stripped)
        if m_deny:
            name = m_deny.group(1)
            if name in all_tools:
                denied.append(name)
            continue
        m_allow = _PERMISSION_ALLOW_RE.match(stripped)
        if m_allow:
            name = m_allow.group(1)
            if name in all_tools:
                allowed.append(name)

    if has_all_yes:
        return all_tools - set(denied)
    if allowed:
        return set(allowed)
    return all_tools
