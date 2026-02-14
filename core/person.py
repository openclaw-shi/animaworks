from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Callable
from datetime import datetime
from pathlib import Path

from core.agent import AgentCore
from core.memory.conversation import ConversationMemory
from core.memory import MemoryManager
from core.messenger import Messenger
from core.paths import load_prompt
from core.schemas import CycleResult, PersonStatus

logger = logging.getLogger("animaworks.person")


class DigitalPerson:
    """A Digital Person: encapsulates identity, memory, agent, and communication.

    1 person = 1 directory.
    """

    def __init__(self, person_dir: Path, shared_dir: Path) -> None:
        self.person_dir = person_dir
        self.name = person_dir.name

        self.memory = MemoryManager(person_dir)
        self.model_config = self.memory.read_model_config()
        self.messenger = Messenger(shared_dir, self.name)
        self.agent = AgentCore(
            person_dir, self.memory, self.model_config, self.messenger
        )

        self._lock = asyncio.Lock()
        self._user_waiting = asyncio.Event()
        # Event NOT set = no user waiting (default state)
        self._status = "idle"
        self._current_task = ""
        self._last_heartbeat: datetime | None = None
        self._last_activity: datetime | None = None
        self._on_lock_released: Callable[[], None] | None = None

        logger.info("DigitalPerson '%s' initialized from %s", self.name, person_dir)

    def set_on_message_sent(
        self, fn: Callable[[str, str, str], None],
    ) -> None:
        """Inject a callback fired after this person sends a message."""
        self.agent.set_on_message_sent(fn)

    def set_on_lock_released(self, fn: Callable[[], None]) -> None:
        """Inject a callback invoked when the person's lock is released."""
        self._on_lock_released = fn

    def _notify_lock_released(self) -> None:
        if self._on_lock_released:
            try:
                self._on_lock_released()
            except Exception:
                logger.exception("[%s] on_lock_released callback failed", self.name)

    # ── Heartbeat history ────────────────────────────────────

    _HEARTBEAT_HISTORY_FILE = "shortterm/heartbeat_history.jsonl"
    _HEARTBEAT_HISTORY_N = 3
    _HEARTBEAT_HISTORY_MAX_LINES = 20

    def _save_heartbeat_history(self, result: CycleResult) -> None:
        """Append heartbeat result summary to JSONL history file."""
        path = self.person_dir / self._HEARTBEAT_HISTORY_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = json.dumps({
            "timestamp": result.timestamp.isoformat(),
            "trigger": result.trigger,
            "action": result.action,
            "summary": result.summary[:500],
            "duration_ms": result.duration_ms,
        }, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        # Keep file bounded
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) > self._HEARTBEAT_HISTORY_MAX_LINES:
            path.write_text(
                "\n".join(lines[-self._HEARTBEAT_HISTORY_MAX_LINES:]) + "\n",
                encoding="utf-8",
            )

    def _load_heartbeat_history(self) -> str:
        """Load last N heartbeat history entries as formatted text."""
        path = self.person_dir / self._HEARTBEAT_HISTORY_FILE
        if not path.exists():
            return ""
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        entries: list[str] = []
        for line in lines[-self._HEARTBEAT_HISTORY_N:]:
            try:
                e = json.loads(line)
                entries.append(
                    f"- {e['timestamp']}: [{e['action']}] {e['summary'][:200]}"
                )
            except (json.JSONDecodeError, KeyError):
                continue
        return "\n".join(entries)

    @property
    def needs_bootstrap(self) -> bool:
        """True if this person has not completed the first-run bootstrap."""
        return (self.person_dir / "bootstrap.md").exists()

    @property
    def status(self) -> PersonStatus:
        return PersonStatus(
            name=self.name,
            status=self._status,
            current_task=self._current_task,
            last_heartbeat=self._last_heartbeat,
            last_activity=self._last_activity,
            pending_messages=self.messenger.unread_count(),
        )

    async def process_message(
        self, content: str, from_person: str = "human"
    ) -> str:
        logger.info(
            "[%s] process_message WAITING from=%s content_len=%d",
            self.name, from_person, len(content),
        )
        self._user_waiting.set()
        try:
            async with self._lock:
                logger.info(
                    "[%s] process_message START (lock acquired) from=%s",
                    self.name, from_person,
                )
                self._status = "thinking"
                self._current_task = f"Responding to {from_person}"

                # Build history-aware prompt via conversation memory
                conv_memory = ConversationMemory(self.person_dir, self.model_config)
                await conv_memory.compress_if_needed()
                prompt = conv_memory.build_chat_prompt(content, from_person)

                try:
                    result = await self.agent.run_cycle(
                        prompt, trigger=f"message:{from_person}"
                    )
                    self._last_activity = datetime.now()

                    # Record the exchange in conversation memory
                    conv_memory.append_turn("human", content)
                    conv_memory.append_turn("assistant", result.summary)
                    conv_memory.save()

                    logger.info(
                        "[%s] process_message END duration_ms=%d",
                        self.name, result.duration_ms,
                    )
                    return result.summary
                except Exception:
                    logger.exception("[%s] process_message FAILED", self.name)
                    raise
                finally:
                    self._status = "idle"
                    self._current_task = ""
        finally:
            self._user_waiting.clear()
            self._notify_lock_released()

    async def process_message_stream(
        self, content: str, from_person: str = "human"
    ) -> AsyncGenerator[dict, None]:
        """Streaming version of process_message.

        Yields stream event dicts. The lock is held for the entire duration.
        """
        logger.info(
            "[%s] process_message_stream WAITING from=%s content_len=%d",
            self.name, from_person, len(content),
        )
        self._user_waiting.set()
        try:
            async with self._lock:
                logger.info(
                    "[%s] process_message_stream START (lock acquired) from=%s",
                    self.name, from_person,
                )
                self._status = "thinking"
                self._current_task = f"Responding to {from_person}"

                # Build history-aware prompt via conversation memory
                conv_memory = ConversationMemory(self.person_dir, self.model_config)
                await conv_memory.compress_if_needed()
                prompt = conv_memory.build_chat_prompt(content, from_person)

                try:
                    async for chunk in self.agent.run_cycle_streaming(
                        prompt, trigger=f"message:{from_person}"
                    ):
                        if chunk.get("type") == "cycle_done":
                            self._last_activity = datetime.now()
                            # Record the exchange in conversation memory
                            cycle_result = chunk.get("cycle_result", {})
                            summary = cycle_result.get("summary", "")
                            conv_memory.append_turn("human", content)
                            conv_memory.append_turn("assistant", summary)
                            conv_memory.save()
                            logger.info(
                                "[%s] process_message_stream END",
                                self.name,
                            )
                        yield chunk
                except Exception:
                    logger.exception("[%s] process_message_stream FAILED", self.name)
                    yield {"type": "error", "message": "Internal error"}
                finally:
                    self._status = "idle"
                    self._current_task = ""
        finally:
            self._user_waiting.clear()
            self._notify_lock_released()

    async def run_heartbeat(self) -> CycleResult:
        # Defer to user messages: skip heartbeat if a user is waiting for the lock
        if self._user_waiting.is_set():
            logger.info("[%s] run_heartbeat SKIPPED: user message waiting", self.name)
            return CycleResult(
                trigger="heartbeat",
                action="skipped",
                summary="User message priority: heartbeat deferred",
            )

        logger.info("[%s] run_heartbeat START", self.name)
        try:
            async with self._lock:
                self._status = "checking"
                self._last_heartbeat = datetime.now()

                hb_config = self.memory.read_heartbeat_config()
                checklist = hb_config or load_prompt("heartbeat_default_checklist")
                parts = [load_prompt("heartbeat", checklist=checklist)]

                # Inject recent heartbeat history for continuity
                history_text = self._load_heartbeat_history()
                if history_text:
                    parts.append(load_prompt(
                        "heartbeat_history", history=history_text,
                    ))

                # Read unread messages but do NOT archive yet.
                # Messages stay in inbox until the agent replies to each sender.
                unread_count = 0
                senders: set[str] = set()
                if self.messenger.has_unread():
                    messages = self.messenger.receive()
                    unread_count = len(messages)
                    senders = {m.from_person for m in messages}
                    logger.info(
                        "[%s] Processing %d unread messages in heartbeat (senders: %s)",
                        self.name, unread_count, ", ".join(senders),
                    )
                    summary = "\n".join(
                        f"- {m.from_person}: {m.content[:800]}" for m in messages
                    )
                    parts.append(load_prompt("unread_messages", summary=summary))

                try:
                    # Reset reply tracking before the cycle
                    self.agent.reset_reply_tracking()

                    result = await self.agent.run_cycle(
                        "\n\n".join(parts), trigger="heartbeat"
                    )
                    self._last_activity = datetime.now()
                    self._save_heartbeat_history(result)

                    # Archive all messages that were injected into the prompt.
                    # In A1 mode agents send replies via Bash (not the
                    # send_message tool), so ToolHandler.replied_to may be
                    # incomplete.  Keeping unarchived messages causes
                    # re-processing and heartbeat cascade loops.
                    if unread_count > 0:
                        replied_to = self.agent.replied_to
                        unreplied = senders - replied_to
                        if unreplied:
                            logger.info(
                                "[%s] No send_message tool calls detected for %s "
                                "(may have replied via Bash)",
                                self.name, ", ".join(unreplied),
                            )
                        total_archived = self.messenger.archive_all()
                        logger.info(
                            "[%s] Archived %d messages from heartbeat",
                            self.name, total_archived,
                        )

                    logger.info(
                        "[%s] run_heartbeat END duration_ms=%d unread_processed=%d",
                        self.name, result.duration_ms, unread_count,
                    )
                    return result
                except Exception:
                    logger.exception("[%s] run_heartbeat FAILED", self.name)
                    raise
                finally:
                    self._status = "idle"
                    self._current_task = ""
        finally:
            self._notify_lock_released()

    async def run_cron_task(
        self, task_name: str, description: str
    ) -> CycleResult:
        logger.info("[%s] run_cron_task START task=%s", self.name, task_name)
        try:
            async with self._lock:
                self._status = "working"
                self._current_task = task_name

                prompt = load_prompt(
                    "cron_task", task_name=task_name, description=description
                )

                try:
                    result = await self.agent.run_cycle(
                        prompt, trigger=f"cron:{task_name}"
                    )
                    self._last_activity = datetime.now()

                    # Record cron execution result
                    self.memory.append_cron_log(
                        task_name,
                        summary=result.summary,
                        duration_ms=result.duration_ms,
                    )

                    logger.info(
                        "[%s] run_cron_task END task=%s duration_ms=%d",
                        self.name, task_name, result.duration_ms,
                    )
                    return result
                except Exception:
                    logger.exception(
                        "[%s] run_cron_task FAILED task=%s", self.name, task_name,
                    )
                    raise
                finally:
                    self._status = "idle"
                    self._current_task = ""
        finally:
            self._notify_lock_released()