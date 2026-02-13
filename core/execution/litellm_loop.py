from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


"""Mode A2 executor: LiteLLM + tool_use loop.

Runs any tool_use-capable model (GPT-4o, Gemini Pro, etc.) in a loop where
the LLM autonomously calls tools until it produces a final text response
or hits the iteration limit.  Session chaining is handled inline when the
context threshold is crossed mid-conversation.
"""

import json as _json
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
    to_litellm_format,
)

logger = logging.getLogger("animaworks.execution.litellm_loop")


class LiteLLMExecutor(BaseExecutor):
    """Execute via LiteLLM with a tool_use loop (Mode A2).

    The LLM calls tools autonomously (memory, files, commands, delegation)
    until it produces a final text response or hits ``max_turns``.
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
        """Build the LiteLLM-format tool list."""
        has_delegate = (
            self._tool_handler.delegate_fn is not None
            and self._model_config.role == "commander"
        )
        external = load_tool_schemas(self._tool_registry, self._personal_tools)
        canonical = build_tool_list(
            include_file_tools=True,
            include_delegate=has_delegate,
            external_schemas=external,
        )
        return to_litellm_format(canonical)

    def _build_llm_kwargs(self) -> dict[str, Any]:
        """Credential + model kwargs for ``litellm.acompletion``."""
        kwargs: dict[str, Any] = {
            "model": self._model_config.model,
            "max_tokens": self._model_config.max_tokens,
        }
        api_key = self._resolve_api_key()
        if api_key:
            kwargs["api_key"] = api_key
        if self._model_config.api_base_url:
            kwargs["api_base"] = self._model_config.api_base_url
        return kwargs

    async def execute(
        self,
        prompt: str,
        system_prompt: str = "",
        tracker: ContextTracker | None = None,
        shortterm: ShortTermMemory | None = None,
    ) -> ExecutionResult:
        """Run the LiteLLM tool-use loop.

        Returns ``ExecutionResult`` with the accumulated response text.
        """
        import litellm

        tools = self._build_tools()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        all_response_text: list[str] = []
        llm_kwargs = self._build_llm_kwargs()
        max_iterations = self._model_config.max_turns
        chain_count = 0

        for iteration in range(max_iterations):
            logger.debug(
                "A2 tool loop iteration=%d messages=%d",
                iteration, len(messages),
            )
            response = await litellm.acompletion(
                messages=messages,
                tools=tools,
                **llm_kwargs,
            )

            choice = response.choices[0]
            message = choice.message

            # ── Context tracking + session chaining ───────────
            if tracker and hasattr(response, "usage") and response.usage:
                usage_dict = {
                    "input_tokens": response.usage.prompt_tokens or 0,
                    "output_tokens": response.usage.completion_tokens or 0,
                }
                threshold_crossed = tracker.update_from_usage(usage_dict)
                if (
                    threshold_crossed
                    and chain_count < self._model_config.max_chains
                    and shortterm is not None
                ):
                    chain_count += 1
                    logger.info(
                        "A2: context threshold crossed at %.1f%%, "
                        "restarting (chain %d/%d)",
                        tracker.usage_ratio * 100,
                        chain_count,
                        self._model_config.max_chains,
                    )
                    current_text = message.content or ""
                    if current_text:
                        all_response_text.append(current_text)
                    shortterm.save(
                        SessionState(
                            session_id="litellm-a2",
                            timestamp=datetime.now().isoformat(),
                            trigger="a2_tool_loop",
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
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": load_prompt("session_continuation")},
                    ]
                    shortterm.clear()
                    continue

            # ── Check for tool calls ──────────────────────────
            tool_calls = message.tool_calls
            if not tool_calls:
                final_text = message.content or ""
                all_response_text.append(final_text)
                logger.debug("A2 final response at iteration=%d", iteration)
                return ExecutionResult(text="\n".join(all_response_text))

            # ── Process tool calls ────────────────────────────
            logger.info(
                "A2 tool calls at iteration=%d: %s",
                iteration,
                ", ".join(tc.function.name for tc in tool_calls),
            )
            messages.append(message.model_dump())

            for tc in tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = _json.loads(tc.function.arguments)
                except _json.JSONDecodeError:
                    fn_args = {}

                if fn_name == "delegate_task":
                    result = await self._tool_handler.handle_delegate(fn_args)
                else:
                    result = self._tool_handler.handle(fn_name, fn_args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        logger.warning("A2 max iterations (%d) reached", max_iterations)
        return ExecutionResult(
            text="\n".join(all_response_text) or "(max iterations reached)",
        )