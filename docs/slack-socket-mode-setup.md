# Slack Socket Mode Setup Guide

Setup instructions for AnimaWorks to receive Slack messages in real time.

## Overview

Socket Mode is a method for receiving events pushed from Slack via WebSocket.
It requires no public URL and works on servers behind NAT.

```
[Slack] ←WebSocket→ [SlackSocketModeManager] → Messenger.receive_external() → [Anima inbox]
                              ↑
                     Started in background within server/app.py lifespan
                     Controlled by config.json external_messaging.slack
```

## Prerequisites

- AnimaWorks server is running
- `slack-bolt` and `aiohttp` are installed (included in `pyproject.toml`)

## 1. Slack App Configuration (Slack Admin Console)

Configure your app at https://api.slack.com/apps.

### Enabling Socket Mode (only when mode=socket)

1. Select "Socket Mode" from the left menu
2. Turn on "Enable Socket Mode"
3. Generate an App-Level Token (scope: `connections:write`)
4. Save the generated `xapp-...` token

This step is not required for Webhook mode (`mode: "webhook"`).

### Event Subscriptions

1. Select "Event Subscriptions" from the left menu
2. Turn on "Enable Events"
3. **Socket Mode**: No Request URL is needed
4. **Webhook mode**: Set Request URL to `https://your-server/api/webhooks/slack/events` (signature verification challenge is handled automatically)
5. Add the following under "Subscribe to bot events":

| Event | Description |
|-------|-------------|
| `message.channels` | Messages in public channels |
| `message.groups` | Messages in private channels |
| `message.im` | Direct messages |
| `message.mpim` | Group DMs |
| `app_mention` | @mentions |

### OAuth Scopes (Bot Token Scopes)

Add the following under "OAuth & Permissions" in the left menu:

| Scope | Purpose |
|-------|---------|
| `channels:history` | Read public channel history |
| `channels:read` | List channels |
| `chat:write` | Send messages |
| `groups:history` | Read private channel history |
| `groups:read` | List private channels |
| `im:history` | Read DM history |
| `im:read` | List DMs |
| `im:write` | Open DMs |
| `mpim:history` | Read group DM history |
| `mpim:read` | List group DMs |
| `users:read` | Retrieve user information |
| `app_mentions:read` | Read @mentions |

### App Home

1. Select "App Home" from the left menu
2. Enable the "Messages Tab"
3. Check "Allow users to send Slash commands and messages from the messages tab"

### Installing to the Workspace

1. Select "Install App" from the left menu
2. Click "Install to Workspace"
3. Save the `xoxb-...` token displayed after authorization

### Inviting the Bot to a Channel

Run `/invite @BotName` in each channel where you want to receive messages.

## 2. Credential Configuration (AnimaWorks Side)

Credentials are resolved in the following priority order: `config.json` → vault → `shared/credentials.json` → environment variables.

Set the following keys in `~/.animaworks/shared/credentials.json`:

```json
{
  "SLACK_BOT_TOKEN": "xoxb-...",
  "SLACK_APP_TOKEN": "xapp-..."
}
```

| Key | Prefix | Purpose |
|-----|--------|---------|
| `SLACK_BOT_TOKEN` | `xoxb-` | Slack API calls (sending messages, retrieving info) |
| `SLACK_APP_TOKEN` | `xapp-` | Establishing the Socket Mode WebSocket connection (only when mode=socket) |

Environment variables can also be used. Credentials can also be configured in the `credentials` section of `config.json`. `SLACK_APP_TOKEN` is not required for Webhook mode.

**Per-Anima Bot**: Use `SLACK_BOT_TOKEN__{anima_name}` and `SLACK_APP_TOKEN__{anima_name}` to configure a dedicated Bot for each Anima. Add these to vault or `shared/credentials.json`.

**Webhook mode with app_id_mapping**: Configure Per-Anima signing secret as `SLACK_SIGNING_SECRET__{anima_name}`.

## 3. config.json Configuration

Add the `external_messaging` section to `~/.animaworks/config.json`:

```json
{
  "external_messaging": {
    "slack": {
      "enabled": true,
      "mode": "socket",
      "anima_mapping": {
        "C0ACT663B5L": "sakura"
      },
      "default_anima": "",
      "app_id_mapping": {}
    }
  }
}
```

### Configuration Options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Enable/disable Slack message reception |
| `mode` | string | `"socket"` | `"socket"` (recommended) or `"webhook"` |
| `anima_mapping` | object | `{}` | Mapping of Slack channel IDs to Anima names (for shared Bot) |
| `default_anima` | string | `""` | Fallback Anima when channel is not in anima_mapping |
| `app_id_mapping` | object | `{}` | Slack API App ID → Anima name (for Webhook mode with multiple Apps) |

### Finding the Channel ID

Right-click a channel name in Slack, select "View channel details", and find the channel ID (starting with `C`) at the bottom. DM IDs start with `D`.

### Differences Between Modes

| Mode | Connection Direction | Public URL | Use Case |
|------|---------------------|------------|----------|
| `socket` | Server → Slack (WebSocket) | Not required | Servers behind NAT (recommended) |
| `webhook` | Slack → Server (HTTP POST) | Required | Public-facing servers |

### Per-Anima Bot (Socket Mode)

You can configure a dedicated Slack Bot for each Anima. Add `SLACK_BOT_TOKEN__{anima_name}` and `SLACK_APP_TOKEN__{anima_name}` to vault or `shared/credentials.json` to start a Socket Mode connection dedicated to that Anima. Per-Anima Bot does not require channel mapping; all messages are delivered to that Anima's inbox.

```json
{
  "SLACK_BOT_TOKEN__sakura": "xoxb-...",
  "SLACK_APP_TOKEN__sakura": "xapp-..."
}
```

Per-Anima Bot and shared Bot (`SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`) can be used together. The shared Bot performs channel-based routing via `anima_mapping` and `default_anima`.

### Additional Webhook Mode Configuration

When `mode: "webhook"`, the following is required:

1. **Request URL**: Set `https://your-server/api/webhooks/slack/events` in Event Subscriptions of the Slack App
2. **Signature verification token**: Set `SLACK_SIGNING_SECRET` in `shared/credentials.json` or as an environment variable

```json
{
  "SLACK_BOT_TOKEN": "xoxb-...",
  "SLACK_SIGNING_SECRET": "Signing Secret from Slack Admin Console"
}
```

| Key | Purpose |
|-----|---------|
| `SLACK_SIGNING_SECRET` | Webhook request signature verification (prevents replay attacks) |

The Signing Secret can be found in the Slack App admin console under "Basic Information" → "App Credentials".

**Using multiple Slack Apps (app_id_mapping)**: Prepare a dedicated Slack App for each Anima and set `app_id_mapping` with `api_app_id → Anima name`. The api_app_id can be found in the Slack App admin console under "Basic Information" (ID starting with `A`). In that case, use Per-Anima signing secret `SLACK_SIGNING_SECRET__{anima_name}`.

## 4. Restart the Server

```bash
animaworks start
```

If the following appears in the startup log, the connection was successful:

```
INFO  animaworks.slack_socket: Shared Slack bot registered (bot_uid=U...)
INFO  animaworks.slack_socket: Slack Socket Mode connected (1 handler(s))
```

When Per-Anima Bot is configured, `Per-Anima Slack bot registered: {name} (bot_uid=U...)` is also displayed.

When disabled, or when `mode: "webhook"`:

```
INFO  animaworks.slack_socket: Slack Socket Mode is disabled
```

In Webhook mode, Socket Mode does not start; events are received via the HTTP endpoint `/api/webhooks/slack/events`.

## Message Flow

1. A Slack user sends a message in a mapped channel
2. Slack sends the event via WebSocket (Socket Mode) or HTTP POST (Webhook)
3. **call_human thread reply**: If the message is a thread reply and mapped via `route_thread_reply`, it is routed to the original Anima's inbox that sent the notification (`core/notification/reply_routing.py`)
4. **Routing resolution**:
   - **Socket Mode Per-Anima Bot**: All messages to that Bot are delivered directly to the corresponding Anima
   - **Socket Mode shared Bot**: `anima_mapping.get(channel_id) or default_anima`
   - **Webhook**: Get Anima via `app_id_mapping.get(api_app_id)` → if not found, use `anima_mapping.get(channel_id) or default_anima`
5. **Intent detection**: For DM or Bot mention, `intent="question"` is attached (`_detect_slack_intent`)
6. `Messenger.receive_external()` places the message at `~/.animaworks/shared/inbox/{anima_name}/{msg_id}.json`
7. The Anima processes the inbox on its next run cycle (heartbeat/cron/manual)

## Related Files

| File | Role |
|------|------|
| `server/slack_socket.py` | SlackSocketModeManager implementation (Socket Mode, supports both Per-Anima and shared Bot) |
| `server/app.py:174-183, 310-312` | Start/stop within lifespan |
| `server/routes/webhooks.py:78-183` | Webhook endpoint (`/api/webhooks/slack/events`, when mode=webhook; supports app_id_mapping and default_anima) |
| `core/messenger.py` | `receive_external()` — inbox placement |
| `core/notification/reply_routing.py` | call_human thread reply routing to Anima |
| `core/config/models.py:181-189` | `ExternalMessagingChannelConfig` / `ExternalMessagingConfig` model |
| `core/tools/slack.py` | Polling-based tools (send/messages/unreplied — coexists) |

## Troubleshooting

### Cannot Connect

- Verify that `SLACK_APP_TOKEN` starts with `xapp-`
- Confirm that Socket Mode is enabled in the Slack App settings
- Confirm that Event Subscriptions are enabled

### Messages Are Not Received

- Verify that the channel IDs in `anima_mapping` are correct
- If `default_anima` is set, confirm that the fallback target is enabled
- Confirm that the Bot has been invited to the target channel
- Check the server logs for `"No anima mapping for channel"` (Socket Mode) or `"No anima mapping for Slack channel %s and no default_anima"` (Webhook)

### Webhook Mode Signature Error (400 Invalid signature)

- Verify that `SLACK_SIGNING_SECRET` (shared) or `SLACK_SIGNING_SECRET__{anima_name}` (when using app_id_mapping) is configured
- Confirm it matches the Signing Secret in "Basic Information" → "App Credentials" of the Slack App admin console
- Check the server logs for `"SLACK_SIGNING_SECRET not configured"`

### Reconnection

- `slack-bolt`'s `AsyncSocketModeHandler` supports automatic reconnection
- WebSocket connections are periodically refreshed approximately every hour
- If rate limiting (429) occurs during long-running operation, restart the server to resolve it

## Limitations

- Socket Mode apps cannot be published to the Slack App Directory (intended for internal tools)
- Maximum concurrent WebSocket connections: 10 per app
- `apps.connections.open` rate limit: 1 per minute
- Processing of messages placed in the inbox depends on the Anima's next run cycle
