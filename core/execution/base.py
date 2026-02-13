from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


"""Base class and result type for execution engines."""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.prompt.context import ContextTracker
from core.schemas import ModelConfig
from core.memory.shortterm import ShortTermMemory


@dataclass
class ExecutionResult:
    """Result of a single execution session.

    Attributes:
        text: The textual response from the LLM.
        result_message: Provider-specific metadata (e.g. ``ResultMessage``
            from Claude Agent SDK).  Used for session chaining in A1 mode.
    """

    text: str
    result_message: Any = field(default=None, repr=False)


class BaseExecutor(ABC):
    """Abstract base for execution engines.

    Each subclass implements one execution mode (A1, A2, B, or fallback).
    Common credential resolution lives here.
    """

    def __init__(
        self,
        model_config: ModelConfig,
        person_dir: Path,
    ) -> None:
        self._model_config = model_config
        self._person_dir = person_dir

    def _resolve_api_key(self) -> str | None:
        """Resolve the actual API key (direct value from config, then env var)."""
        if self._model_config.api_key:
            return self._model_config.api_key
        return os.environ.get(self._model_config.api_key_env)

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        system_prompt: str = "",
        tracker: ContextTracker | None = None,
        shortterm: ShortTermMemory | None = None,
    ) -> ExecutionResult:
        """Run the execution engine and return the response.

        Args:
            prompt: The user/trigger prompt.
            system_prompt: Assembled system prompt (not used by Mode B).
            tracker: Context usage tracker (not used by Mode B).
            shortterm: Short-term memory for session chaining (A2/fallback).

        Returns:
            ExecutionResult with the response text and optional metadata.
        """
        ...