from __future__ import annotations
# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0
#
# This file is part of AnimaWorks core/server, licensed under Apache-2.0.
# See LICENSE for the full license text.

"""Slack Socket Mode integration for real-time message reception."""

import asyncio
import collections
import json
import logging
import time

from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from core.config.models import load_config
from core.messenger import Messenger
from core.paths import get_data_dir
from core.tools._base import get_credential, _lookup_vault_credential, _lookup_shared_credentials

logger = logging.getLogger("animaworks.slack_socket")

# ── Dedup: prevent same Slack message from being delivered twice ──
# When both message and app_mention events fire for a single @-mention,
# the first handler to process stores the ts; the second skips it.
_DEDUP_TTL_SEC = 10
_recent_ts: collections.OrderedDict[str, float] = collections.OrderedDict()


def _is_duplicate_ts(ts: str) -> bool:
    """Return True if *ts* was already processed within the TTL window."""
    now = time.monotonic()
    while _recent_ts and next(iter(_recent_ts.values())) < now - _DEDUP_TTL_SEC:
        _recent_ts.popitem(last=False)
    if ts in _recent_ts:
        return True
    _recent_ts[ts] = now
    return False


def _detect_slack_intent(text: str, channel_id: str, bot_user_id: str) -> str:
    """Return ``"question"`` if the message is a DM or mentions the bot."""
    if channel_id.startswith("D"):
        return "question"
    if bot_user_id and f"<@{bot_user_id}>" in (text or ""):
        return "question"
    return ""


async def _resolve_bot_user_id(app: AsyncApp) -> str:
    """Call ``auth.test`` once and return the bot's Slack user ID."""
    try:
        resp = await app.client.auth_test()
        return resp.get("user_id", "") or ""
    except Exception:
        logger.warning("Failed to resolve bot user ID via auth.test", exc_info=True)
        return ""


class SlackSocketModeManager:
    """Manages Slack Socket Mode WebSocket connections.

    Supports multiple per-Anima bots alongside an optional shared bot.
    Each per-Anima bot runs its own AsyncApp + AsyncSocketModeHandler,
    with messages routed directly to the corresponding Anima inbox.
    """

    def __init__(self) -> None:
        self._handlers: list[AsyncSocketModeHandler] = []
        self._apps: list[AsyncApp] = []
        self._bot_user_ids: dict[str, str] = {}

    async def start(self) -> None:
        """Start Socket Mode connections if enabled in config."""
        config = load_config()
        slack_config = config.external_messaging.slack
        if not slack_config.enabled or slack_config.mode != "socket":
            logger.info("Slack Socket Mode is disabled")
            return

        for anima_name in self._discover_per_anima_bots():
            bot_token = self._get_per_anima_credential("SLACK_BOT_TOKEN", anima_name)
            app_token = self._get_per_anima_credential("SLACK_APP_TOKEN", anima_name)
            if bot_token and app_token:
                try:
                    app = AsyncApp(token=bot_token)
                    bot_uid = await _resolve_bot_user_id(app)
                    self._bot_user_ids[anima_name] = bot_uid
                    self._register_per_anima_handler(app, anima_name, bot_uid)
                    handler = AsyncSocketModeHandler(app, app_token)
                    self._apps.append(app)
                    self._handlers.append(handler)
                    logger.info("Per-Anima Slack bot registered: %s (bot_uid=%s)", anima_name, bot_uid)
                except Exception:
                    logger.exception(
                        "Failed to set up per-Anima Slack bot for '%s'", anima_name,
                    )

        try:
            shared_bot = get_credential("slack", "slack_socket", env_var="SLACK_BOT_TOKEN")
            shared_app_token = get_credential("slack_app", "slack_socket", env_var="SLACK_APP_TOKEN")
            app = AsyncApp(token=shared_bot)
            shared_bot_uid = await _resolve_bot_user_id(app)
            self._bot_user_ids["__shared__"] = shared_bot_uid
            self._register_shared_handler(app, slack_config.anima_mapping, slack_config.default_anima, shared_bot_uid)
            handler = AsyncSocketModeHandler(app, shared_app_token)
            self._apps.append(app)
            self._handlers.append(handler)
            logger.info("Shared Slack bot registered (bot_uid=%s)", shared_bot_uid)
        except Exception:
            if not self._handlers:
                raise
            logger.info("Shared Slack bot not configured; per-Anima bots only")

        if self._handlers:
            await asyncio.gather(*(h.connect_async() for h in self._handlers))
            logger.info(
                "Slack Socket Mode connected (%d handler(s))", len(self._handlers),
            )

    @staticmethod
    def _discover_per_anima_bots() -> list[str]:
        """Scan vault/shared credentials for SLACK_BOT_TOKEN__* keys."""
        found: set[str] = set()
        prefix = "SLACK_BOT_TOKEN__"

        try:
            from core.config.vault import get_vault_manager

            vm = get_vault_manager()
            data = vm.load_vault()
            shared_section = data.get("shared") or {}
            for key in shared_section:
                if key.startswith(prefix):
                    found.add(key[len(prefix):])
        except Exception:
            pass

        try:
            cred_file = get_data_dir() / "shared" / "credentials.json"
            if cred_file.is_file():
                data = json.loads(cred_file.read_text(encoding="utf-8"))
                for key in data:
                    if key.startswith(prefix):
                        found.add(key[len(prefix):])
        except Exception:
            pass

        return sorted(found)

    @staticmethod
    def _get_per_anima_credential(base_key: str, anima_name: str) -> str | None:
        """Resolve a per-Anima credential (e.g. SLACK_BOT_TOKEN__sumire)."""
        key = f"{base_key}__{anima_name}"
        token = _lookup_vault_credential(key)
        if token:
            return token
        return _lookup_shared_credentials(key)

    def _register_per_anima_handler(self, app: AsyncApp, anima_name: str, bot_user_id: str = "") -> None:
        """Register event handler that routes all messages to a specific Anima."""

        @app.event("message")
        async def handle_message(event: dict, say) -> None:  # noqa: ARG001
            if "subtype" in event:
                return

            ts = event.get("ts", "")
            if _is_duplicate_ts(ts):
                return

            try:
                from core.notification.reply_routing import route_thread_reply

                if route_thread_reply(event, get_data_dir() / "shared"):
                    return
            except Exception:
                logger.debug("Reply routing lookup failed", exc_info=True)

            text = event.get("text", "")
            channel_id = event.get("channel", "")
            intent = _detect_slack_intent(text, channel_id, bot_user_id)

            shared_dir = get_data_dir() / "shared"
            messenger = Messenger(shared_dir, anima_name)
            messenger.receive_external(
                content=text,
                source="slack",
                source_message_id=ts,
                external_user_id=event.get("user", ""),
                external_channel_id=channel_id,
                intent=intent,
            )
            logger.info(
                "Per-Anima Socket Mode message routed: channel=%s -> anima=%s (intent=%s)",
                channel_id,
                anima_name,
                intent or "none",
            )

        @app.event("app_mention")
        async def handle_app_mention(event: dict, say) -> None:  # noqa: ARG001
            ts = event.get("ts", "")
            if _is_duplicate_ts(ts):
                return

            text = event.get("text", "")
            channel_id = event.get("channel", "")

            shared_dir = get_data_dir() / "shared"
            messenger = Messenger(shared_dir, anima_name)
            messenger.receive_external(
                content=text,
                source="slack",
                source_message_id=ts,
                external_user_id=event.get("user", ""),
                external_channel_id=channel_id,
                intent="question",
            )
            logger.info(
                "Per-Anima Socket Mode app_mention routed: channel=%s -> anima=%s",
                channel_id,
                anima_name,
            )

    def _register_shared_handler(
        self, app: AsyncApp, anima_mapping: dict[str, str], default_anima: str = "",
        bot_user_id: str = "",
    ) -> None:
        """Register event handler for the shared bot (channel-based routing)."""

        @app.event("message")
        async def handle_message(event: dict, say) -> None:  # noqa: ARG001
            if "subtype" in event:
                return

            ts = event.get("ts", "")
            if _is_duplicate_ts(ts):
                return

            try:
                from core.notification.reply_routing import route_thread_reply

                if route_thread_reply(event, get_data_dir() / "shared"):
                    return
            except Exception:
                logger.debug("Reply routing lookup failed", exc_info=True)

            channel_id = event.get("channel", "")
            anima_name = anima_mapping.get(channel_id) or default_anima
            if not anima_name:
                logger.debug(
                    "No anima mapping for channel %s and no default_anima; ignoring",
                    channel_id,
                )
                return

            text = event.get("text", "")
            intent = _detect_slack_intent(text, channel_id, bot_user_id)

            shared_dir = get_data_dir() / "shared"
            messenger = Messenger(shared_dir, anima_name)
            messenger.receive_external(
                content=text,
                source="slack",
                source_message_id=ts,
                external_user_id=event.get("user", ""),
                external_channel_id=channel_id,
                intent=intent,
            )
            logger.info(
                "Shared Socket Mode message routed: channel=%s -> anima=%s (intent=%s)",
                channel_id,
                anima_name,
                intent or "none",
            )

        @app.event("app_mention")
        async def handle_app_mention(event: dict, say) -> None:  # noqa: ARG001
            ts = event.get("ts", "")
            if _is_duplicate_ts(ts):
                return

            channel_id = event.get("channel", "")
            anima_name_resolved = anima_mapping.get(channel_id) or default_anima
            if not anima_name_resolved:
                logger.debug(
                    "No anima mapping for channel %s (app_mention); ignoring",
                    channel_id,
                )
                return

            text = event.get("text", "")

            shared_dir = get_data_dir() / "shared"
            messenger = Messenger(shared_dir, anima_name_resolved)
            messenger.receive_external(
                content=text,
                source="slack",
                source_message_id=ts,
                external_user_id=event.get("user", ""),
                external_channel_id=channel_id,
                intent="question",
            )
            logger.info(
                "Shared Socket Mode app_mention routed: channel=%s -> anima=%s",
                channel_id,
                anima_name_resolved,
            )

    async def stop(self) -> None:
        """Disconnect all Socket Mode handlers gracefully."""
        for handler in self._handlers:
            try:
                await handler.close_async()
            except Exception:
                logger.exception("Error closing Socket Mode handler")
        self._handlers.clear()
        self._apps.clear()
        logger.info("Slack Socket Mode disconnected")

    @property
    def is_connected(self) -> bool:
        """Return whether any Socket Mode handler is active."""
        return len(self._handlers) > 0
