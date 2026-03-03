---
name: slack-tool
description: >-
  Slack integration tool. Send/receive messages, search, check unreplied, list channels.
  "slack" "channel" "thread"
tags: [communication, slack, external]
---

# Slack Tool

External tool for Slack messaging, search, and channel management.

## Invocation via use_tool

```json
{"tool": "use_tool", "arguments": {"tool_name": "slack", "action": "ACTION", "args": {...}}}
```

## Actions

### send — Send message
```json
{"tool_name": "slack", "action": "send", "args": {"channel": "#channel-name", "message": "text", "thread": "thread ts (optional)"}}
```

### messages — Get messages
```json
{"tool_name": "slack", "action": "messages", "args": {"channel": "#channel-name", "limit": 20}}
```

### search — Search messages
```json
{"tool_name": "slack", "action": "search", "args": {"keyword": "search term", "channel": "#channel (optional)", "limit": 50}}
```

### unreplied — Check unreplied messages
```json
{"tool_name": "slack", "action": "unreplied", "args": {}}
```

### channels — List channels
```json
{"tool_name": "slack", "action": "channels", "args": {}}
```

## CLI Usage (S-mode)

```bash
animaworks-tool slack send CHANNEL MESSAGE [--thread TS]
animaworks-tool slack messages CHANNEL [-n 20]
animaworks-tool slack search KEYWORD [-c CHANNEL] [-n 50]
animaworks-tool slack unreplied [--json]
animaworks-tool slack channels
```

## Notes

- Slack Bot Token must be configured in credentials
- Channel can be specified with # prefix or by channel ID
