"""Unit tests for SlackChannel bot_token mode."""
# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.notification.channels.slack import SlackChannel


# ── Helpers ──────────────────────────────────────────────────


def _make_channel(config: dict) -> SlackChannel:
    """Create a SlackChannel with given config."""
    ch = SlackChannel.__new__(SlackChannel)
    ch._config = config
    return ch


# ── TestBotTokenMode ─────────────────────────────────────────


class TestBotTokenMode:
    """Tests for Slack bot_token API mode."""

    @pytest.mark.asyncio
    async def test_bot_token_sends_to_api(self):
        """Bot token mode sends to chat.postMessage API."""
        ch = _make_channel({"bot_token": "xoxb-test", "channel": "C123"})

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await ch.send("Test Subject", "Test Body")

        assert result == "slack: OK"
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://slack.com/api/chat.postMessage"
        assert call_args[1]["headers"]["Authorization"] == "Bearer xoxb-test"
        assert call_args[1]["json"]["channel"] == "C123"

    @pytest.mark.asyncio
    async def test_bot_token_missing_channel_error(self):
        """Bot token mode without channel returns error."""
        ch = _make_channel({"bot_token": "xoxb-test"})
        result = await ch.send("Subject", "Body")
        assert "channel not configured" in result

    @pytest.mark.asyncio
    async def test_bot_token_api_error(self):
        """Bot token mode handles Slack API error response."""
        ch = _make_channel({"bot_token": "xoxb-test", "channel": "C123"})

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": False, "error": "channel_not_found"}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await ch.send("Test", "Body")

        assert "channel_not_found" in result

    @pytest.mark.asyncio
    async def test_bot_token_exception_no_token_leak(self):
        """Exception handling does not leak bot_token in error message."""
        ch = _make_channel({"bot_token": "xoxb-secret-token-123", "channel": "C123"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = RuntimeError("connection error with secret stuff")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await ch.send("Test", "Body")

        # The returned error message should NOT contain the token
        assert "xoxb-secret-token-123" not in result
        assert "request failed" in result

    @pytest.mark.asyncio
    async def test_no_token_no_webhook_error(self):
        """Neither bot_token nor webhook_url returns error."""
        ch = _make_channel({})
        ch._resolve_env = MagicMock(return_value="")
        from core.tools._base import ToolConfigError
        with patch("core.tools._base.get_credential", side_effect=ToolConfigError("no cred")):
            result = await ch.send("Subject", "Body")
        assert "neither bot_token nor webhook_url configured" in result

    @pytest.mark.asyncio
    async def test_priority_prefix_in_text(self):
        """High priority adds prefix to message."""
        ch = _make_channel({"bot_token": "xoxb-test", "channel": "C123"})

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await ch.send("Alert", "Something bad", priority="urgent")

        text = mock_client.post.call_args[1]["json"]["text"]
        assert "[URGENT]" in text


class TestUsernameOverride:
    """Tests for per-Anima username/icon_url override."""

    @pytest.mark.asyncio
    async def test_username_set_when_anima_name_provided(self):
        """When anima_name is given, payload includes username override."""
        ch = _make_channel({"bot_token": "xoxb-test", "channel": "C123"})

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await ch.send("Report", "All good", anima_name="sakura")

        payload = mock_client.post.call_args[1]["json"]
        assert payload["username"] == "sakura"
        # "(from sakura)" should NOT appear in text when username override is active
        assert "(from sakura)" not in payload["text"]

    @pytest.mark.asyncio
    async def test_no_username_when_anima_name_empty(self):
        """When anima_name is empty, no username override in payload."""
        ch = _make_channel({"bot_token": "xoxb-test", "channel": "C123"})

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await ch.send("Report", "All good")

        payload = mock_client.post.call_args[1]["json"]
        assert "username" not in payload
        assert "icon_url" not in payload

    @pytest.mark.asyncio
    async def test_icon_url_from_template(self):
        """When icon_url_template is configured, icon_url is set in payload."""
        ch = _make_channel({
            "bot_token": "xoxb-test",
            "channel": "C123",
            "icon_url_template": "https://cdn.example.com/{name}/icon.png",
        })

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await ch.send("Report", "Body", anima_name="mei")

        payload = mock_client.post.call_args[1]["json"]
        assert payload["username"] == "mei"
        assert payload["icon_url"] == "https://cdn.example.com/mei/icon.png"

    @pytest.mark.asyncio
    async def test_no_icon_url_without_template(self):
        """When no icon_url_template, no icon_url in payload."""
        ch = _make_channel({"bot_token": "xoxb-test", "channel": "C123"})

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await ch.send("Report", "Body", anima_name="rin")

        payload = mock_client.post.call_args[1]["json"]
        assert payload["username"] == "rin"
        assert "icon_url" not in payload


class TestWebhookFallback:
    """Tests for webhook mode fallback."""

    @pytest.mark.asyncio
    async def test_falls_back_to_webhook(self):
        """When no bot_token, falls back to webhook mode."""
        ch = _make_channel({"webhook_url": "https://hooks.slack.com/test"})
        ch._resolve_env = MagicMock(return_value="")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        from core.tools._base import ToolConfigError

        with patch("core.tools._base.get_credential", side_effect=ToolConfigError("no cred")), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await ch.send("Test", "Body")

        assert result == "slack: OK"
        call_url = mock_client.post.call_args[0][0]
        assert call_url == "https://hooks.slack.com/test"
