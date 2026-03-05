from __future__ import annotations

# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0
#
# This file is part of AnimaWorks core/server, licensed under Apache-2.0.
# See LICENSE for the full license text.


"""Dynamic tool guide generation for Mode S (CLI) and Mode A (schema).

.. deprecated::
    External tools are now accessed via ``use_tool`` (Mode B) or
    skill+CLI (Mode A/S).  ``build_tools_guide()`` returns an empty
    string.  ``load_tool_schemas()`` delegates to
    ``schemas.load_all_tool_schemas()``.
"""

import logging
from typing import Any

logger = logging.getLogger("animaworks.tool_guide")


# ── Public API ───────────────────────────────────────────────────


def build_tools_guide(
    tool_registry: list[str],
    personal_tools: dict[str, str] | None = None,
) -> str:
    """Build a compact summary table of allowed external tools.

    .. deprecated::
        External tools are now accessed via ``use_tool`` with skill-based
        documentation.  This function returns an empty string.
    """
    return ""


def load_tool_schemas(
    tool_registry: list[str],
    personal_tools: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Load structured schemas for Mode A.

    Delegates to ``schemas.load_all_tool_schemas()`` which handles both
    core and personal tool modules with consistent normalisation.
    """
    from core.tooling.schemas import load_all_tool_schemas

    return load_all_tool_schemas(
        tool_registry=tool_registry,
        personal_tools=personal_tools,
    )
