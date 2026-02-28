from __future__ import annotations
# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0

"""InboxMixin -- Anima-to-Anima message (inbox) processing.

Extracted from ``core.anima.DigitalAnima`` as a Mixin.  All ``self``
references are resolved at runtime via MRO when mixed into ``DigitalAnima``.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from core.time_utils import now_jst

from core.execution._sanitize import (
    ORIGIN_ANIMA,
    ORIGIN_EXTERNAL_PLATFORM,
    ORIGIN_HUMAN,
    ORIGIN_UNKNOWN,
)
from core.memory.streaming_journal import StreamingJournal
from core.messenger import InboxItem
from core.paths import load_prompt
from core.i18n import t
from core.schemas import CycleResult

logger = logging.getLogger("animaworks.anima")

# Maximum time (seconds) an unreplied message stays in inbox before
# force-archival.  Prevents re-processing storms when replied_to tracking
# fails (e.g. agent replies via board post instead of DM).
# With a typical heartbeat interval of 5 min, a message gets ~2 chances
# to be replied to before force-archival.
_STALE_MESSAGE_TIMEOUT_SEC = 600

_SOURCE_TO_ORIGIN: dict[str, str] = {
    "slack": ORIGIN_EXTERNAL_PLATFORM,
    "chatwork": ORIGIN_EXTERNAL_PLATFORM,
    "human": ORIGIN_HUMAN,
    "anima": ORIGIN_ANIMA,
}


@dataclass
class InboxResult:
    """Result of inbox message processing."""

    inbox_items: list[InboxItem] = field(default_factory=list)
    messages: list[Any] = field(default_factory=list)
    senders: set[str] = field(default_factory=set)
    unread_count: int = 0
    prompt_parts: list[str] = field(default_factory=list)


class InboxMixin:
    """Mixin: Anima-to-Anima inbox processing, filtering, dedup, archiving."""

    # ── Inbox MSG Immediate Processing ────────────────────────

    async def process_inbox_message(
        self,
        cascade_suppressed_senders: set[str] | None = None,
    ) -> CycleResult:
        """Process Anima-to-Anima messages immediately under _inbox_lock.

        Separated from heartbeat to provide instant response to inter-Anima
        messages without triggering the full heartbeat observation cycle.
        """
        self._interrupt_event.clear()
        logger.info("[%s] process_inbox_message START", self.name)
        try:
            async with self._inbox_lock:
                self._status_slots["inbox"] = "processing"

                self._activity.log("inbox_processing_start", summary=t("anima.inbox_start"))

                inbox_result: InboxResult | None = None
                try:
                    inbox_result = await self._process_inbox_messages(
                        cascade_suppressed_senders,
                    )

                    if inbox_result.unread_count == 0:
                        logger.info("[%s] process_inbox_message: no messages", self.name)
                        return CycleResult(
                            trigger="inbox",
                            action="idle",
                            summary="No unread messages",
                        )

                    senders_str = ", ".join(inbox_result.senders)
                    trigger = f"inbox:{senders_str}"

                    task_delegation_rules = load_prompt("task_delegation_rules")
                    messages_text = "\n\n".join(inbox_result.prompt_parts)
                    prompt = load_prompt(
                        "inbox_message",
                        messages=messages_text,
                        task_delegation_rules=task_delegation_rules,
                    )

                    # Suppress board fanout when replying to board_mention
                    has_board_mention = any(
                        item.msg.type == "board_mention"
                        for item in inbox_result.inbox_items
                    )
                    from core.tooling.handler import suppress_board_fanout, active_session_type
                    _fanout_token = suppress_board_fanout.set(True) if has_board_mention else None
                    _session_token = self.agent._tool_handler.set_active_session_type("inbox")

                    self.agent.reset_reply_tracking(session_type="inbox")
                    self.agent.reset_posted_channels(session_type="inbox")

                    journal = StreamingJournal(self.anima_dir, session_type="inbox")
                    journal.open(trigger=trigger, from_person=senders_str)

                    accumulated_text = ""
                    result: CycleResult | None = None

                    try:
                        async for chunk in self.agent.run_cycle_streaming(
                            prompt, trigger=trigger,
                        ):
                            if chunk.get("type") == "text_delta":
                                accumulated_text += chunk.get("text", "")
                                journal.write_text(chunk.get("text", ""))

                            if chunk.get("type") == "cycle_done":
                                cycle_result = chunk.get("cycle_result", {})
                                result = CycleResult(
                                    trigger=trigger,
                                    action=cycle_result.get("action", "responded"),
                                    summary=cycle_result.get("summary", ""),
                                    duration_ms=cycle_result.get("duration_ms", 0),
                                    context_usage_ratio=cycle_result.get(
                                        "context_usage_ratio", 0.0
                                    ),
                                    session_chained=cycle_result.get(
                                        "session_chained", False
                                    ),
                                    total_turns=cycle_result.get("total_turns", 0),
                                )
                                journal.finalize(summary=result.summary[:500])

                        if result is None:
                            result = CycleResult(
                                trigger=trigger,
                                action="responded",
                                summary=accumulated_text[:500] or "(no result)",
                            )
                    finally:
                        journal.close()
                        if _fanout_token is not None:
                            suppress_board_fanout.reset(_fanout_token)
                        active_session_type.reset(_session_token)

                    self._last_activity = now_jst()

                    # Archive processed messages
                    await self._archive_processed_messages(
                        inbox_result.inbox_items,
                        inbox_result.senders,
                        self.agent.replied_to,
                    )

                    self._activity.log(
                        "inbox_processing_end",
                        summary=result.summary[:200],
                        meta={"senders": list(inbox_result.senders), "count": inbox_result.unread_count},
                    )

                    logger.info(
                        "[%s] process_inbox_message END duration_ms=%d unread=%d",
                        self.name, result.duration_ms, inbox_result.unread_count,
                    )
                    return result

                except Exception as exc:
                    logger.exception("[%s] process_inbox_message FAILED", self.name)
                    # Archive on crash to prevent re-processing storms
                    if inbox_result is not None and inbox_result.inbox_items:
                        try:
                            self.messenger.archive_paths(inbox_result.inbox_items)
                        except Exception:
                            logger.warning(
                                "[%s] Failed to crash-archive inbox messages",
                                self.name, exc_info=True,
                            )
                    self._activity.log(
                        "error",
                        summary=t("anima.inbox_error", exc=type(exc).__name__),
                        meta={"phase": "process_inbox_message", "error": str(exc)[:200]},
                    )
                    raise
                finally:
                    self._status_slots["inbox"] = "idle"
                    self._task_slots["inbox"] = ""
        finally:
            self._notify_lock_released()

    async def _process_inbox_messages(
        self,
        cascade_suppressed_senders: set[str] | None = None,
    ) -> InboxResult:
        """Read, filter, deduplicate, format, and record inbox messages.

        Handles cascade suppression, MessageDeduplicator, retry counter,
        episode recording, and activity logging.
        """
        if not self.messenger.has_unread():
            return InboxResult()

        inbox_items = self.messenger.receive_with_paths()
        messages = [item.msg for item in inbox_items]
        unread_count = len(messages)
        senders: set[str] = {m.from_person for m in messages}

        # ── Filter cascade-suppressed senders ──
        if cascade_suppressed_senders:
            suppressed_items = [
                item for item in inbox_items
                if item.msg.from_person in cascade_suppressed_senders
            ]
            inbox_items = [
                item for item in inbox_items
                if item.msg.from_person not in cascade_suppressed_senders
            ]
            messages = [item.msg for item in inbox_items]
            if suppressed_items:
                logger.info(
                    "[%s] Cascade-suppressed %d messages from %s",
                    self.name, len(suppressed_items),
                    ", ".join(cascade_suppressed_senders & senders),
                )
            senders = {m.from_person for m in messages}
            unread_count = len(messages)

        # ── Message deduplication (Phase 4) ──
        try:
            from core.memory.dedup import MessageDeduplicator
            dedup = MessageDeduplicator(self.anima_dir)

            # Load previously deferred messages and prepend to inbox
            deferred_raw = dedup.load_deferred()
            if deferred_raw:
                from core.schemas import Message as _Msg
                for raw in deferred_raw:
                    try:
                        deferred_msg = _Msg(
                            from_person=raw.get("from", "unknown"),
                            to_person=self.name,
                            content=raw.get("content", ""),
                            type=raw.get("type", "message"),
                        )
                        messages.append(deferred_msg)
                    except Exception:
                        logger.debug("[%s] Skipping invalid deferred message", self.name)
                logger.info("[%s] Restored %d deferred messages", self.name, len(deferred_raw))

            # Apply rate limiting first (before consolidation)
            messages, rate_deferred = dedup.apply_rate_limit(messages)
            if rate_deferred:
                dedup.archive_suppressed(rate_deferred)

            # Consolidate same-sender messages
            messages, consolidated_suppressed = dedup.consolidate_messages(messages)
            if consolidated_suppressed:
                dedup.archive_suppressed(consolidated_suppressed)

            # Suppress resolved topics
            try:
                resolutions = self.memory.read_resolutions(days=7)
            except Exception:
                resolutions = []
            if resolutions:
                filtered = []
                for m in messages:
                    if dedup.is_resolved_topic(m.content, resolutions):
                        dedup.archive_suppressed([m])
                    else:
                        filtered.append(m)
                messages = filtered

            # Update counts after dedup
            unread_count = len(messages)
            senders = {m.from_person for m in messages}
        except Exception:
            logger.debug("[%s] Message dedup failed, using original messages", self.name, exc_info=True)

        logger.info(
            "[%s] Processing %d unread messages in heartbeat (senders: %s)",
            self.name, unread_count, ", ".join(senders),
        )

        # ── Retry counter: track how many times each inbox message is presented ──
        _read_counts_path = self.anima_dir / "state" / "inbox_read_counts.json"
        _read_counts: dict[str, int] = {}
        try:
            if _read_counts_path.exists():
                _read_counts = json.loads(
                    _read_counts_path.read_text(encoding="utf-8")
                )
        except Exception:
            _read_counts = {}

        for item in inbox_items:
            key = item.path.name
            _read_counts[key] = _read_counts.get(key, 0) + 1

        # Prune entries for inbox files that no longer exist
        inbox_dir = self.anima_dir.parent.parent / "shared" / "inbox" / self.name
        _read_counts = {
            k: v for k, v in _read_counts.items()
            if (inbox_dir / k).exists()
        }

        try:
            _read_counts_path.write_text(
                json.dumps(_read_counts, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            logger.debug("[%s] Failed to write inbox_read_counts", self.name, exc_info=True)

        # Format messages with retry annotations
        prompt_parts: list[str] = []
        lines: list[str] = []
        for item in inbox_items:
            m = item.msg
            count = _read_counts.get(item.path.name, 1)
            if count >= 2:
                prefix = t("anima.unread_prefix", from_person=m.from_person, count=count)
            else:
                prefix = f"- {m.from_person}: "
            lines.append(f"{prefix}{m.content[:800]}")
        # Deferred messages (no InboxItem) are appended without counter
        for m in messages:
            if not any(item.msg is m for item in inbox_items):
                lines.append(f"- {m.from_person}: {m.content[:800]}")
        summary = "\n".join(lines)
        prompt_parts.append(load_prompt("unread_messages", summary=summary))

        # Record received message content to episodes so that
        # inter-Anima communications survive in episodic memory.
        _msg_ts = now_jst().strftime("%H:%M")
        _recordable = [m for m in messages if m.type != "ack"]
        if len(_recordable) > 50:
            logger.warning(
                "[%s] DM burst: %d messages, recording first 50",
                self.name, len(_recordable),
            )
        for _m in _recordable[:50]:
            _episode = t(
                "anima.msg_received_episode",
                ts=_msg_ts,
                from_person=_m.from_person,
                content=_m.content[:1000],
            ) + "\n"
            try:
                self.memory.append_episode(_episode)
            except Exception:
                logger.debug(
                    "[%s] Failed to record message episode from %s",
                    self.name, _m.from_person, exc_info=True,
                )

        # Activity log: message received (full content, summary truncated)
        for _m in _recordable[:50]:
            _msg_origin = _SOURCE_TO_ORIGIN.get(_m.source, ORIGIN_UNKNOWN)
            _msg_origin_chain = _m.origin_chain if _m.origin_chain else [_msg_origin]
            self._activity.log(
                "message_received",
                content=_m.content,
                summary=_m.content[:200],
                from_person=_m.from_person,
                to_person=self.name,
                meta={"from_type": _m.source},
                origin=_msg_origin,
                origin_chain=_msg_origin_chain,
            )

        return InboxResult(
            inbox_items=inbox_items,
            messages=messages,
            senders=senders,
            unread_count=unread_count,
            prompt_parts=prompt_parts,
        )

    async def _archive_processed_messages(
        self,
        inbox_items: list[InboxItem],
        senders: set[str],
        replied_to: set[str],
    ) -> None:
        """Archive replied-to messages; force-archive stale unreplied messages.

        Messages from unreplied senders stay in inbox for the next
        heartbeat cycle.
        """
        unreplied = senders - replied_to

        items_to_archive = [
            item for item in inbox_items
            if item.msg.from_person in replied_to
            or item.msg.from_person not in senders  # system msgs
        ]
        items_to_keep = [
            item for item in inbox_items
            if item not in items_to_archive
        ]

        # Safety: force-archive messages that have been sitting
        # in inbox longer than _STALE_MESSAGE_TIMEOUT_SEC to
        # prevent re-processing storms even if replied_to
        # tracking fails.
        if items_to_keep:
            now = time.time()
            stale: list[InboxItem] = []
            for item in items_to_keep:
                try:
                    mtime = item.path.stat().st_mtime
                    if (now - mtime) > _STALE_MESSAGE_TIMEOUT_SEC:
                        stale.append(item)
                except FileNotFoundError:
                    continue  # already archived/deleted
            if stale:
                logger.warning(
                    "[%s] Force-archiving %d stale unreplied "
                    "messages (>%ds old)",
                    self.name, len(stale),
                    _STALE_MESSAGE_TIMEOUT_SEC,
                )
                items_to_archive.extend(stale)
                items_to_keep = [
                    i for i in items_to_keep if i not in stale
                ]

        if unreplied and items_to_keep:
            logger.warning(
                "[%s] Unreplied messages from %s will remain "
                "in inbox for next heartbeat cycle",
                self.name, ", ".join(unreplied),
            )

        total_archived = self.messenger.archive_paths(
            items_to_archive
        )
        logger.info(
            "[%s] Archived %d/%d messages "
            "(kept %d unreplied in inbox)",
            self.name, total_archived, len(inbox_items),
            len(items_to_keep),
        )
