from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


"""Anthropic SDK fallback executor.

Used when the Claude Agent SDK is not available but the model is Claude.
Calls the Anthropic messages API directly with tool_use for memory operations.
Handles mid-conversation context monitoring and session chaining.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from core.prompt.context import ContextTracker
from core.execution.base import BaseExecutor, ExecutionResult
from core.memory import MemoryManager
from core.paths import load_prompt
from core.prompt.builder import build_system_prompt, inject_shortterm
from core.schemas import ModelConfig
from core.memory.shortterm import SessionState, ShortTermMemory
from core.tooling.handler import ToolHandler
from core.tooling.guide import load_tool_schemas
from core.tooling.schemas import (
    build_tool_list,
    to_anthropic_format,
)

logger = logging.getLogger("animaworks.execution.anthropic_fallback")


class AnthropicFallbackExecutor(BaseExecutor):
    """Fallback: use Anthropic SDK with tool_use for memory ops.

    Mid-conversation context monitoring: if the threshold is crossed,
    state is externalized and the conversation is restarted with
    restored short-term memory.
    """

    def __init__(
        self,
        model_config: ModelConfig,
        person_dir: Path,
        tool_handler: ToolHandler,
        tool_registry: list[str],
        memory: MemoryManager,
        personal_tools: dict[str, str] | None = None,
    ) -> None:
        super().__init__(model_config, person_dir)
        self._tool_handler = tool_handler
        self._tool_registry = tool_registry
        self._memory = memory
        self._personal_tools = personal_tools or {}

    def _build_tools(self) -> list[dict[str, Any]]:
        """Build the Anthropic-format tool list."""
        has_delegate = (
            self._tool_handler.delegate_fn is not None
            and self._model_config.role == "commander"
        )
        external = load_tool_schemas(self._tool_registry, self._personal_tools)
        canonical = build_tool_list(
            include_file_tools=False,
            include_delegate=has_delegate,
            external_schemas=external,
        )
        return to_anthropic_format(canonical)

    async def execute(
        self,
        prompt: str,
        system_prompt: str = "",
        tracker: ContextTracker | None = None,
        shortterm: ShortTermMemory | None = None,
    ) -> ExecutionResult:
        """Run Anthropic SDK with tool_use loop."""
        import anthropic

        client_kwargs: dict[str, str] = {}
        api_key = self._resolve_api_key()
        if api_key:
            client_kwargs["api_key"] = api_key
        if self._model_config.api_base_url:
            client_kwargs["base_url"] = self._model_config.api_base_url
        client = anthropic.AsyncAnthropic(**client_kwargs)

        tools = self._build_tools()
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        all_response_text: list[str] = []
        chain_count = 0

        for iteration in range(10):
            logger.debug(
                "API call iteration=%d messages_count=%d",
                iteration, len(messages),
            )
            response = await client.messages.create(
                model=self._model_config.model,
                max_tokens=self._model_config.max_tokens,
                system=system_prompt,
                messages=messages,
                tools=tools,
            )

            # ── Context tracking + session chaining ───────────
            if tracker:
                usage_dict = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }
                threshold_crossed = tracker.update_from_usage(usage_dict)

                if (
                    threshold_crossed
                    and chain_count < self._model_config.max_chains
                    and shortterm is not None
                ):
                    chain_count += 1
                    logger.info(
                        "Anthropic SDK: context threshold crossed at %.1f%%, "
                        "restarting with short-term memory (chain %d/%d)",
                        tracker.usage_ratio * 100,
                        chain_count,
                        self._model_config.max_chains,
                    )
                    current_text = "\n".join(
                        b.text for b in response.content if b.type == "text"
                    )
                    all_response_text.append(current_text)

                    shortterm.save(
                        SessionState(
                            session_id="anthropic-fallback",
                            timestamp=datetime.now().isoformat(),
                            trigger="anthropic_sdk",
                            original_prompt=prompt,
                            accumulated_response="\n".join(all_response_text),
                            context_usage_ratio=tracker.usage_ratio,
                            turn_count=iteration,
                        )
                    )

                    tracker.reset()
                    system_prompt = inject_shortterm(
                        build_system_prompt(
                            self._memory,
                            tool_registry=self._tool_registry,
                            personal_tools=self._personal_tools,
                        ),
                        shortterm,
                    )
                    messages = [
                        {"role": "user", "content": load_prompt("session_continuation")}
                    ]
                    shortterm.clear()
                    continue

            # ── Check for tool use ────────────────────────────
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                logger.debug("Final response received at iteration=%d", iteration)
                final_text = "\n".join(
                    b.text for b in response.content if b.type == "text"
                )
                all_response_text.append(final_text)
                return ExecutionResult(text="\n".join(all_response_text))

            # ── Process tool calls ────────────────────────────
            logger.info(
                "Tool calls at iteration=%d: %s",
                iteration, ", ".join(tu.name for tu in tool_uses),
            )
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tu in tool_uses:
                if tu.name == "delegate_task":
                    result = await self._tool_handler.handle_delegate(tu.input)
                else:
                    result = self._tool_handler.handle(tu.name, tu.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result,
                })
            messages.append({"role": "user", "content": tool_results})

        logger.warning("Max iterations (10) reached, returning fallback response")
        return ExecutionResult(
            text="\n".join(all_response_text) or "(max iterations reached)",
        )