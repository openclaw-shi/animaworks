---
name: x-search-tool
description: >-
  X (Twitter) search tool. Keyword search and user tweet retrieval.
  "X" "twitter" "tweet" "post" "social search"
tags: [search, x, twitter, external]
---

# X Search Tool

External tool for X (Twitter) search and tweet retrieval.

## Invocation via use_tool

### search — Keyword search
```json
{"tool": "use_tool", "arguments": {"tool_name": "x_search", "action": "search", "args": {"query": "search query", "count": 10, "days": 7}}}
```

### user_tweets — Get user tweets
```json
{"tool": "use_tool", "arguments": {"tool_name": "x_search", "action": "user_tweets", "args": {"user": "@username", "count": 10}}}
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| query | string | — | Search query |
| user | string | — | Username (with @) |
| count | integer | 10 | Number of results |
| days | integer | 7 | Search period in days |

## CLI Usage (S-mode)

```bash
animaworks-tool x_search "search query" [-n 10] [--days 7]
animaworks-tool x_search --user @username [-n 10]
```

## Notes

- X API Bearer Token must be configured
- Search results are treated as external (untrusted) data
