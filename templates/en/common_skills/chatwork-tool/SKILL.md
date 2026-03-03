---
name: chatwork-tool
description: >-
  Chatwork integration tool. Send/receive messages, search, check unreplied, list rooms.
  "chatwork" "CW" "unreplied" "room" "mention"
tags: [communication, chatwork, external]
---

# Chatwork Tool

External tool for Chatwork messaging, search, and room management.

## Invocation via use_tool

```json
{"tool": "use_tool", "arguments": {"tool_name": "chatwork", "action": "ACTION", "args": {...}}}
```

## Actions

### send — Send message
```json
{"tool_name": "chatwork", "action": "send", "args": {"room": "room name or ID", "message": "text"}}
```

### messages — Get messages
```json
{"tool_name": "chatwork", "action": "messages", "args": {"room": "room name or ID", "limit": 20}}
```

### search — Search messages
```json
{"tool_name": "chatwork", "action": "search", "args": {"keyword": "search term", "room": "room (optional)", "limit": 50}}
```

### unreplied — Check unreplied messages
```json
{"tool_name": "chatwork", "action": "unreplied", "args": {}}
```

### rooms — List rooms
```json
{"tool_name": "chatwork", "action": "rooms", "args": {}}
```

### mentions — Get mentions
```json
{"tool_name": "chatwork", "action": "mentions", "args": {}}
```

### delete — Delete message (own messages only)
```json
{"tool_name": "chatwork", "action": "delete", "args": {"room": "room name or ID", "message_id": "message ID"}}
```

## CLI Usage (S-mode)

```bash
animaworks-tool chatwork send ROOM MESSAGE
animaworks-tool chatwork messages ROOM [-n 20]
animaworks-tool chatwork search KEYWORD [-r ROOM] [-n 50]
animaworks-tool chatwork unreplied [--json]
animaworks-tool chatwork rooms
animaworks-tool chatwork mentions [--json]
```

## Notes

- Chatwork API Token must be configured in credentials
- Room can be specified by name or room ID
