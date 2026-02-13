from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


"""Mode B executor: assisted (1-shot, framework handles memory I/O).

The framework reads memory, injects context, calls the LLM once without
tools, then records the episode and extracts knowledge.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from core.prompt.context import ContextTracker
from core.execution.base import BaseExecutor, ExecutionResult
from core.memory import MemoryManager
from core.schemas import ModelConfig
from core.memory.shortterm import ShortTermMemory

logger = logging.getLogger("animaworks.execution.assisted")


class AssistedExecutor(BaseExecutor):
    """Execute in assisted mode (Mode B).

    Flow:
      1. Pre-call:  inject identity + recent episodes + keyword-matched knowledge
      2. LLM 1-shot call (no tools)
      3. Post-call: record episode
      4. Post-call: extract knowledge (additional 1-shot)
    """

    def __init__(
        self,
        model_config: ModelConfig,
        person_dir: Path,
        memory: MemoryManager,
    ) -> None:
        super().__init__(model_config, person_dir)
        self._memory = memory

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
    ) -> Any:
        """Call LiteLLM ``acompletion`` and return the raw response."""
        import litellm

        kwargs: dict[str, Any] = {
            "model": self._model_config.model,
            "messages": messages,
            "max_tokens": self._model_config.max_tokens,
        }

        if system:
            kwargs["messages"] = [
                {"role": "system", "content": system}
            ] + messages

        api_key = self._resolve_api_key()
        if api_key:
            kwargs["api_key"] = api_key
        if self._model_config.api_base_url:
            kwargs["api_base"] = self._model_config.api_base_url

        return await litellm.acompletion(**kwargs)

    async def execute(
        self,
        prompt: str,
        system_prompt: str = "",
        tracker: ContextTracker | None = None,
        shortterm: ShortTermMemory | None = None,
    ) -> ExecutionResult:
        """Run the assisted execution flow."""
        logger.info("_run_assisted START prompt_len=%d", len(prompt))

        # ── 1. Pre-call: gather context ──────────────────
        identity = self._memory.read_identity()
        injection = self._memory.read_injection()
        recent_episodes = self._memory.read_recent_episodes(days=7)

        # Simple keyword extraction for knowledge search
        keywords = set(re.findall(r"[\w]{3,}", prompt))
        knowledge_hits: list[str] = []
        for kw in list(keywords)[:10]:
            for fname, line in self._memory.search_memory_text(kw, scope="knowledge"):
                knowledge_hits.append(f"[{fname}] {line}")
        knowledge_context = "\n".join(dict.fromkeys(knowledge_hits))  # dedupe

        # Build enriched system prompt
        system_parts = [identity, injection]
        if recent_episodes:
            system_parts.append(f"## 直近の行動ログ\n\n{recent_episodes[:4000]}")
        if knowledge_context:
            system_parts.append(f"## 関連知識\n\n{knowledge_context[:4000]}")
        system = "\n\n---\n\n".join(p for p in system_parts if p)

        # ── 2. LLM 1-shot call ───────────────────────────
        messages = [{"role": "user", "content": prompt}]
        response = await self._call_llm(messages, system=system)
        reply = response.choices[0].message.content or ""
        logger.info("_run_assisted LLM replied, len=%d", len(reply))

        # ── 3. Post-call: record episode ─────────────────
        ts = datetime.now().strftime("%H:%M")
        episode = f"- {ts} [assisted] prompt: {prompt[:200]}… → reply: {reply[:200]}…"
        self._memory.append_episode(episode)

        # ── 4. Post-call: knowledge extraction ───────────
        try:
            extract_messages = [
                {
                    "role": "user",
                    "content": (
                        "以下のやりとりから、今後の判断に役立つ教訓や事実があれば"
                        "1〜3行で要約してください。なければ「なし」とだけ答えてください。\n\n"
                        f"質問: {prompt[:1000]}\n\n回答: {reply[:1000]}"
                    ),
                }
            ]
            extract_resp = await self._call_llm(extract_messages)
            extracted = extract_resp.choices[0].message.content or ""
            if extracted.strip() and extracted.strip() != "なし":
                topic = datetime.now().strftime("learned_%Y%m%d_%H%M%S")
                self._memory.write_knowledge(topic, extracted.strip())
                logger.info("Knowledge extracted: %s", extracted[:100])
        except Exception:
            logger.debug("Knowledge extraction failed", exc_info=True)

        return ExecutionResult(text=reply)