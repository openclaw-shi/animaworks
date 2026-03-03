---
name: chatwork-tool
description: >-
  Chatwork連携ツール。メッセージ送信・受信・検索・未返信確認・ルーム一覧取得を行う。
  「チャットワーク」「Chatwork」「CW」「未返信」「ルーム」「メンション」
tags: [communication, chatwork, external]
---

# Chatwork ツール

Chatworkのメッセージ送受信・検索・管理を行う外部ツール。

## use_tool での呼び出し

```json
{"tool": "use_tool", "arguments": {"tool_name": "chatwork", "action": "ACTION", "args": {...}}}
```

## アクション一覧

### send — メッセージ送信
```json
{"tool_name": "chatwork", "action": "send", "args": {"room": "ルーム名またはID", "message": "送信テキスト"}}
```

### messages — メッセージ取得
```json
{"tool_name": "chatwork", "action": "messages", "args": {"room": "ルーム名またはID", "limit": 20}}
```

### search — メッセージ検索
```json
{"tool_name": "chatwork", "action": "search", "args": {"keyword": "検索ワード", "room": "ルーム名(任意)", "limit": 50}}
```

### unreplied — 未返信メッセージ確認
```json
{"tool_name": "chatwork", "action": "unreplied", "args": {}}
```

### rooms — ルーム一覧
```json
{"tool_name": "chatwork", "action": "rooms", "args": {}}
```

### mentions — メンション取得
```json
{"tool_name": "chatwork", "action": "mentions", "args": {}}
```

### delete — メッセージ削除（自分の発言のみ）
```json
{"tool_name": "chatwork", "action": "delete", "args": {"room": "ルーム名またはID", "message_id": "メッセージID"}}
```

### sync — メッセージ同期（キャッシュ更新）
```json
{"tool_name": "chatwork", "action": "sync", "args": {"room": "ルーム名またはID"}}
```

## CLI使用法（Sモード）

```bash
animaworks-tool chatwork send ROOM MESSAGE
animaworks-tool chatwork messages ROOM [-n 20]
animaworks-tool chatwork search KEYWORD [-r ROOM] [-n 50]
animaworks-tool chatwork unreplied [--json]
animaworks-tool chatwork rooms
animaworks-tool chatwork mentions [--json]
animaworks-tool chatwork delete ROOM MESSAGE_ID
animaworks-tool chatwork sync [ROOM]
```

## 注意事項

- API Token は credentials に事前設定が必要
- roomはルーム名でもルームIDでも指定可能
- 送信には書き込み用トークンが必要な場合がある
