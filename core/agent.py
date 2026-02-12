from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.context_tracker import ContextTracker
from core.memory import MemoryManager
from core.messenger import Messenger
from core.paths import load_prompt
from core.prompt_builder import build_system_prompt, inject_shortterm
from core.schemas import CycleResult, ModelConfig
from core.shortterm_memory import SessionState, ShortTermMemory

logger = logging.getLogger("animaworks.agent")


class AgentCore:
    """Wraps Claude Agent SDK to provide thinking/acting for a Digital Person."""

    def __init__(
        self,
        person_dir: Path,
        memory: MemoryManager,
        model_config: ModelConfig | None = None,
        messenger: Messenger | None = None,
    ) -> None:
        self.person_dir = person_dir
        self.memory = memory
        self.model_config = model_config or ModelConfig()
        self.messenger = messenger
        self._sdk_available = self._check_sdk()

        logger.info(
            "AgentCore: model=%s, api_key_env=%s, base_url=%s",
            self.model_config.model,
            self.model_config.api_key_env,
            self.model_config.api_base_url or "(default)",
        )

    def _check_sdk(self) -> bool:
        try:
            from claude_agent_sdk import query  # noqa: F401

            return True
        except ImportError:
            logger.warning(
                "claude-agent-sdk not available, falling back to anthropic SDK"
            )
            return False

    async def run_cycle(
        self, prompt: str, trigger: str = "manual"
    ) -> CycleResult:
        """Run one agent cycle with autonomous memory search.

        If the context threshold is crossed, the session is externalized
        to short-term memory and automatically continued in a fresh session.
        """
        start = time.monotonic()
        shortterm = ShortTermMemory(self.person_dir)
        tracker = ContextTracker(
            model=self.model_config.model,
            threshold=self.model_config.context_threshold,
        )

        # Build system prompt; inject short-term memory from prior session
        system_prompt = build_system_prompt(self.memory)
        if shortterm.has_pending():
            system_prompt = inject_shortterm(system_prompt, shortterm)
            logger.info("Injected short-term memory into system prompt")

        # Run the primary session
        if self._sdk_available:
            result, result_msg = await self._run_with_agent_sdk(
                system_prompt, prompt, tracker
            )
        else:
            result = await self._run_with_anthropic_sdk(
                system_prompt, prompt, tracker, shortterm
            )
            result_msg = None

        # Session chaining: if threshold was crossed, continue in a new session
        session_chained = False
        total_turns = result_msg.num_turns if result_msg else 0
        chain_count = 0

        while (
            self._sdk_available
            and tracker.threshold_exceeded
            and chain_count < self.model_config.max_chains
        ):
            session_chained = True
            chain_count += 1
            logger.info(
                "Session chain %d/%d: context at %.1f%%",
                chain_count,
                self.model_config.max_chains,
                tracker.usage_ratio * 100,
            )

            # Always save fresh state (clear stale data first)
            shortterm.clear()
            shortterm.save(
                SessionState(
                    session_id=result_msg.session_id if result_msg else "",
                    timestamp=datetime.now().isoformat(),
                    trigger=trigger,
                    original_prompt=prompt,
                    accumulated_response=result,
                    context_usage_ratio=tracker.usage_ratio,
                    turn_count=result_msg.num_turns if result_msg else 0,
                )
            )

            # New session with restored short-term memory
            tracker.reset()
            system_prompt_2 = inject_shortterm(
                build_system_prompt(self.memory),
                shortterm,
            )
            continuation_prompt = load_prompt("session_continuation")
            try:
                result_2, result_msg_2 = await self._run_with_agent_sdk(
                    system_prompt_2, continuation_prompt, tracker
                )
            except Exception:
                logger.exception(
                    "Chained session %d failed; preserving short-term memory",
                    chain_count,
                )
                break
            result = result + "\n" + result_2
            result_msg = result_msg_2
            if result_msg_2:
                total_turns += result_msg_2.num_turns

        # Clean up short-term memory after successful completion
        shortterm.clear()

        duration_ms = int((time.monotonic() - start) * 1000)
        return CycleResult(
            trigger=trigger,
            action="responded",
            summary=result,
            duration_ms=duration_ms,
            context_usage_ratio=tracker.usage_ratio,
            session_chained=session_chained,
            total_turns=total_turns,
        )

    def _resolve_api_key(self) -> str | None:
        """Resolve the actual API key from the configured environment variable."""
        return os.environ.get(self.model_config.api_key_env)

    # ── Agent SDK path ──────────────────────────────────────

    async def _run_with_agent_sdk(
        self,
        system_prompt: str,
        prompt: str,
        tracker: ContextTracker,
    ) -> tuple[str, Any | None]:
        """Run a session via Claude Agent SDK with context monitoring hook.

        Returns ``(response_text, ResultMessage | None)``.
        The second element is typed as ``Any | None`` to avoid importing
        ``ResultMessage`` at module level.
        """
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            HookMatcher,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )
        from claude_agent_sdk.types import (
            HookContext,
            HookInput,
            PostToolUseHookSpecificOutput,
            SyncHookJSONOutput,
        )

        threshold = self.model_config.context_threshold
        _hook_fired = False

        async def _post_tool_hook(
            input_data: HookInput,
            tool_use_id: str | None,
            context: HookContext,
        ) -> SyncHookJSONOutput:
            nonlocal _hook_fired
            transcript_path = input_data.get("transcript_path", "")
            ratio = tracker.estimate_from_transcript(transcript_path)

            if ratio >= threshold and not _hook_fired:
                _hook_fired = True
                logger.info(
                    "PostToolUse hook: context at %.1f%%, injecting save instruction",
                    ratio * 100,
                )
                return SyncHookJSONOutput(
                    hookSpecificOutput=PostToolUseHookSpecificOutput(
                        hookEventName="PostToolUse",
                        additionalContext=(
                            f"コンテキスト使用率が{ratio:.0%}に達しました。"
                            "shortterm/session_state.md に現在の作業状態を書き出してください。"
                            "内容: 何をしていたか、どこまで進んだか、次に何をすべきか。"
                            "書き出し後、作業を中断してその旨を報告してください。"
                        ),
                    )
                )
            return SyncHookJSONOutput()

        # Build env dict so the child process uses per-person credentials
        env: dict[str, str] = {}
        api_key = self._resolve_api_key()
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
        if self.model_config.api_base_url:
            env["ANTHROPIC_BASE_URL"] = self.model_config.api_base_url

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
            permission_mode="acceptEdits",
            cwd=str(self.person_dir),
            max_turns=self.model_config.max_turns,
            model=self.model_config.model,
            env=env,
            hooks={
                "PostToolUse": [HookMatcher(matcher=None, hooks=[_post_tool_hook])],
            },
        )

        response_text: list[str] = []
        result_message: ResultMessage | None = None
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_message = message
                tracker.update_from_result_message(message.usage)
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_text.append(block.text)

        return "\n".join(response_text) or "(no response)", result_message

    # ── Anthropic SDK fallback path ─────────────────────────

    async def _run_with_anthropic_sdk(
        self,
        system_prompt: str,
        prompt: str,
        tracker: ContextTracker,
        shortterm: ShortTermMemory,
    ) -> str:
        """Fallback: use anthropic SDK with tool_use for memory ops.

        Mid-conversation context monitoring: if the threshold is crossed,
        state is externalized and the conversation is restarted with
        restored short-term memory.
        """
        import anthropic

        api_key = self._resolve_api_key()
        client_kwargs: dict[str, str] = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if self.model_config.api_base_url:
            client_kwargs["base_url"] = self.model_config.api_base_url
        client = anthropic.AsyncAnthropic(**client_kwargs)

        tools = self._build_anthropic_tools()
        messages: list[dict] = [{"role": "user", "content": prompt}]
        all_response_text: list[str] = []
        chain_count = 0

        for iteration in range(10):
            response = await client.messages.create(
                model=self.model_config.model,
                max_tokens=self.model_config.max_tokens,
                system=system_prompt,
                messages=messages,
                tools=tools,
            )

            # Track context usage from API response
            usage_dict = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
            threshold_crossed = tracker.update_from_usage(usage_dict)

            if threshold_crossed and chain_count < self.model_config.max_chains:
                chain_count += 1
                logger.info(
                    "Anthropic SDK: context threshold crossed at %.1f%%, "
                    "restarting with short-term memory (chain %d/%d)",
                    tracker.usage_ratio * 100,
                    chain_count,
                    self.model_config.max_chains,
                )
                # Collect text so far
                current_text = "\n".join(
                    b.text for b in response.content if b.type == "text"
                )
                all_response_text.append(current_text)

                # Save state
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

                # Restart with fresh context + short-term memory
                tracker.reset()
                system_prompt = inject_shortterm(
                    build_system_prompt(self.memory), shortterm
                )
                messages = [
                    {"role": "user", "content": load_prompt("session_continuation")}
                ]
                shortterm.clear()
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                final_text = "\n".join(
                    b.text for b in response.content if b.type == "text"
                )
                all_response_text.append(final_text)
                return "\n".join(all_response_text)

            messages.append(
                {"role": "assistant", "content": response.content}
            )
            tool_results = []
            for tu in tool_uses:
                result = self._handle_tool_call(tu.name, tu.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": result,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        return "\n".join(all_response_text) or "(max iterations reached)"

    # ── Tool definitions (Anthropic SDK fallback) ───────────

    @staticmethod
    def _build_anthropic_tools() -> list[dict]:
        return [
            {
                "name": "search_memory",
                "description": "Search the person's long-term memory by keyword.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search keyword",
                        },
                        "scope": {
                            "type": "string",
                            "enum": [
                                "knowledge",
                                "episodes",
                                "procedures",
                                "all",
                            ],
                            "description": "Memory category to search",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "read_memory_file",
                "description": "Read a specific memory file by relative path.",
                "input_schema": {
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
                "description": "Write or append to a memory file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "mode": {
                            "type": "string",
                            "enum": ["overwrite", "append"],
                        },
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "send_message",
                "description": "Send a message to another person. The recipient will be notified immediately.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient person name",
                        },
                        "content": {
                            "type": "string",
                            "description": "Message content",
                        },
                        "reply_to": {
                            "type": "string",
                            "description": "Message ID to reply to (optional)",
                        },
                        "thread_id": {
                            "type": "string",
                            "description": "Thread ID to continue a conversation (optional)",
                        },
                    },
                    "required": ["to", "content"],
                },
            },
        ]

    def _handle_tool_call(self, name: str, args: dict) -> str:
        if name == "search_memory":
            results = self.memory.search_knowledge(args.get("query", ""))
            if not results:
                return f"No results for '{args.get('query', '')}'"
            return "\n".join(
                f"- {fname}: {line}" for fname, line in results[:10]
            )

        if name == "read_memory_file":
            path = self.person_dir / args["path"]
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8")
            return f"File not found: {args['path']}"

        if name == "write_memory_file":
            path = self.person_dir / args["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            if args.get("mode") == "append":
                with open(path, "a", encoding="utf-8") as f:
                    f.write(args["content"])
            else:
                path.write_text(args["content"], encoding="utf-8")
            return f"Written to {args['path']}"

        if name == "send_message":
            if not self.messenger:
                return "Error: messenger not configured"
            msg = self.messenger.send(
                to=args["to"],
                content=args["content"],
                thread_id=args.get("thread_id", ""),
                reply_to=args.get("reply_to", ""),
            )
            return f"Message sent to {args['to']} (id: {msg.id}, thread: {msg.thread_id})"

        return f"Unknown tool: {name}"
