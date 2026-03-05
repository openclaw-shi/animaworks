from __future__ import annotations
# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0
#
# This file is part of AnimaWorks core/server, licensed under Apache-2.0.
# See LICENSE for the full license text.

"""Slack Socket Mode integration for real-time message reception."""

import asyncio
import json
import logging

from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from core.config.models import load_config
from core.messenger import Messenger
from core.paths import get_data_dir
from core.tools._base import get_credential, _lookup_vault_credential, _lookup_shared_credentials

logger = logging.getLogger("animaworks.slack_socket")


class SlackSocketModeManager:
    """Manages Slack Socket Mode WebSocket connections.

    Supports multiple per-Anima bots alongside an optional shared bot.
    Each per-Anima bot runs its own AsyncApp + AsyncSocketModeHandler,
    with messages routed directly to the corresponding Anima inbox.
    """

    def __init__(self) -> None:
        self._handlers: list[AsyncSocketModeHandler] = []
        self._apps: list[AsyncApp] = []

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
                    self._register_per_anima_handler(app, anima_name)
                    handler = AsyncSocketModeHandler(app, app_token)
                    self._apps.append(app)
                    self._handlers.append(handler)
                    logger.info("Per-Anima Slack bot registered: %s", anima_name)
                except Exception:
                    logger.exception(
                        "Failed to set up per-Anima Slack bot for '%s'", anima_name,
                    )

        try:
            shared_bot = get_credential("slack", "slack_socket", env_var="SLACK_BOT_TOKEN")
            shared_app_token = get_credential("slack_app", "slack_socket", env_var="SLACK_APP_TOKEN")
            app = AsyncApp(token=shared_bot)
            self._register_shared_handler(app, slack_config.anima_mapping, slack_config.default_anima)
            handler = AsyncSocketModeHandler(app, shared_app_token)
            self._apps.append(app)
            self._handlers.append(handler)
            logger.info("Shared Slack bot registered")
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

    def _register_per_anima_handler(self, app: AsyncApp, anima_name: str) -> None:
        """Register event handler that routes all messages to a specific Anima."""

        @app.event("message")
        async def handle_message(event: dict, say) -> None:  # noqa: ARG001
            if "subtype" in event:
                return

            try:
                from core.notification.reply_routing import route_thread_reply

                if route_thread_reply(event, get_data_dir() / "shared"):
                    return
            except Exception:
                logger.debug("Reply routing lookup failed", exc_info=True)

            shared_dir = get_data_dir() / "shared"
            messenger = Messenger(shared_dir, anima_name)
            messenger.receive_external(
                content=event.get("text", ""),
                source="slack",
                source_message_id=event.get("ts", ""),
                external_user_id=event.get("user", ""),
                external_channel_id=event.get("channel", ""),
            )
            logger.info(
                "Per-Anima Socket Mode message routed: channel=%s -> anima=%s",
                event.get("channel", ""),
                anima_name,
            )

    def _register_shared_handler(
        self, app: AsyncApp, anima_mapping: dict[str, str], default_anima: str = "",
    ) -> None:
        """Register event handler for the shared bot (channel-based routing)."""

        @app.event("message")
        async def handle_message(event: dict, say) -> None:  # noqa: ARG001
            if "subtype" in event:
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

            shared_dir = get_data_dir() / "shared"
            messenger = Messenger(shared_dir, anima_name)
            messenger.receive_external(
                content=event.get("text", ""),
                source="slack",
                source_message_id=event.get("ts", ""),
                external_user_id=event.get("user", ""),
                external_channel_id=channel_id,
            )
            logger.info(
                "Shared Socket Mode message routed: channel=%s -> anima=%s",
                channel_id,
                anima_name,
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
