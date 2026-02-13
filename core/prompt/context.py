# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.

"""Context window usage tracker.

Monitors token consumption and detects when the 50% threshold is crossed.
Uses transcript file size as a heuristic for the Agent SDK path,
and direct usage data from the Anthropic SDK fallback path.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("animaworks.context_tracker")

# Approximate characters per token (tunable constant).
# JSON transcripts are verbose, so 4 chars/token is a reasonable estimate.
CHARS_PER_TOKEN = 4

# Context window sizes per model family (input tokens).
# Keys are matched as prefixes against the model name (after stripping provider/).
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic
    "claude-sonnet-4": 200_000,
    "claude-sonnet-3.5": 200_000,
    "claude-opus-4": 200_000,
    "claude-haiku-3.5": 200_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "o1": 200_000,
    "o3": 200_000,
    # Google
    "gemini-2.0-flash": 1_048_576,
    "gemini-2.5-pro": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
    # Ollama / local (conservative defaults)
    "gemma3": 128_000,
    "llama3": 128_000,
    "qwen2.5": 128_000,
}
_DEFAULT_CONTEXT_WINDOW = 128_000


def _resolve_context_window(model: str) -> int:
    """Return the context window size for the given model name.

    Strips the ``provider/`` prefix (e.g. ``openai/gpt-4o`` → ``gpt-4o``)
    before matching.
    """
    bare = model.split("/", 1)[-1] if "/" in model else model
    for prefix, size in MODEL_CONTEXT_WINDOWS.items():
        if bare.startswith(prefix):
            return size
    return _DEFAULT_CONTEXT_WINDOW


@dataclass
class ContextTracker:
    """Tracks context window usage across an agent session.

    Two estimation modes:
      1. Transcript-based (Agent SDK): file size of transcript_path ÷ CHARS_PER_TOKEN
      2. Usage-based (Anthropic SDK / ResultMessage): direct input_tokens from API
    """

    model: str = "claude-sonnet-4-20250514"
    threshold: float = 0.50

    # Internal state
    _last_ratio: float = field(default=0.0, init=False, repr=False)
    _threshold_hit: bool = field(default=False, init=False, repr=False)
    _input_tokens: int = field(default=0, init=False, repr=False)
    _output_tokens: int = field(default=0, init=False, repr=False)

    @property
    def context_window(self) -> int:
        return _resolve_context_window(self.model)

    @property
    def usage_ratio(self) -> float:
        return self._last_ratio

    @property
    def threshold_exceeded(self) -> bool:
        return self._threshold_hit

    # ── Transcript-based estimation (Agent SDK) ────────────

    def estimate_from_transcript(self, transcript_path: str) -> float:
        """Estimate context usage ratio from transcript file size.

        Returns the estimated ratio (0.0–1.0+).
        """
        if not transcript_path:
            return self._last_ratio
        try:
            file_size = os.path.getsize(transcript_path)
        except OSError:
            return self._last_ratio

        estimated_tokens = file_size // CHARS_PER_TOKEN
        ratio = estimated_tokens / self.context_window
        self._last_ratio = ratio

        if not self._threshold_hit and ratio >= self.threshold:
            self._threshold_hit = True
            logger.warning(
                "Context threshold %.0f%% exceeded (transcript estimate): "
                "~%d tokens / %d window (%.1f%%)",
                self.threshold * 100,
                estimated_tokens,
                self.context_window,
                ratio * 100,
            )

        return ratio

    # ── Usage-based tracking (Anthropic SDK / ResultMessage) ─

    def update_from_usage(self, usage: dict) -> bool:
        """Update from Anthropic API response.usage dict.

        For the Anthropic SDK path, ``input_tokens`` already reflects the
        *entire* context size (system prompt + all prior messages + tool
        results).  Using ``input_tokens`` alone is the correct measure of
        how full the context window is — output_tokens from prior turns
        are already included in the next request's input_tokens.

        Returns True if the threshold was newly crossed.
        """
        self._input_tokens = usage.get("input_tokens", 0)
        self._output_tokens = usage.get("output_tokens", 0)

        # input_tokens alone represents context fullness
        self._last_ratio = (
            self._input_tokens / self.context_window
            if self.context_window
            else 0.0
        )

        if not self._threshold_hit and self._last_ratio >= self.threshold:
            self._threshold_hit = True
            logger.warning(
                "Context threshold %.0f%% exceeded (API usage): "
                "%d input_tokens / %d window (%.1f%%)",
                self.threshold * 100,
                self._input_tokens,
                self.context_window,
                self._last_ratio * 100,
            )
            return True
        return False

    def update_from_result_message(self, usage: dict | None) -> None:
        """Update from Agent SDK ResultMessage.usage (post-session snapshot)."""
        if not usage:
            return
        self._input_tokens = usage.get("input_tokens", 0)
        self._output_tokens = usage.get("output_tokens", 0)
        total = self._input_tokens + self._output_tokens
        self._last_ratio = total / self.context_window if self.context_window else 0.0

        if not self._threshold_hit and self._last_ratio >= self.threshold:
            self._threshold_hit = True

    def reset(self) -> None:
        """Reset tracker for a new session."""
        self._last_ratio = 0.0
        self._threshold_hit = False
        self._input_tokens = 0
        self._output_tokens = 0