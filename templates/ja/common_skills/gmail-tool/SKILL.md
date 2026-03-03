---
name: gmail-tool
description: >-
  Gmail連携ツール。未読メール確認・本文読み取り・下書き作成。OAuth2認証でGmail APIに直接アクセス。
  「Gmail」「メール」「未読」「下書き」「受信」
tags: [communication, gmail, email, external]
---

# Gmail ツール

GmailのメールをOAuth2で直接操作する外部ツール。

## use_tool での呼び出し

```json
{"tool": "use_tool", "arguments": {"tool_name": "gmail", "action": "ACTION", "args": {...}}}
```

## アクション一覧

### unread — 未読メール一覧
```json
{"tool_name": "gmail", "action": "unread", "args": {"max_results": 20}}
```

### read_body — メール本文読み取り
```json
{"tool_name": "gmail", "action": "read_body", "args": {"message_id": "メッセージID"}}
```

### draft — 下書き作成
```json
{"tool_name": "gmail", "action": "draft", "args": {"to": "宛先アドレス", "subject": "件名", "body": "本文", "thread_id": "スレッドID(任意)"}}
```

## CLI使用法（Sモード）

```bash
animaworks-tool gmail unread [-n 20]
animaworks-tool gmail read MESSAGE_ID
animaworks-tool gmail draft --to ADDR --subject SUBJ --body BODY [--thread-id TID]
```

## 注意事項

- 初回使用時にOAuth2認証フローが必要
- credentials.json と token.json が ~/.animaworks/ に配置されること
