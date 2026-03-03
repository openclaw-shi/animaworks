---
name: x-search-tool
description: >-
  X（Twitter）検索ツール。キーワード検索とユーザーツイート取得。
  「X」「Twitter」「ツイート」「ポスト」「SNS検索」
tags: [search, x, twitter, external]
---

# X Search ツール

X (Twitter) の検索・ツイート取得を行う外部ツール。

## use_tool での呼び出し

### search — キーワード検索
```json
{"tool": "use_tool", "arguments": {"tool_name": "x_search", "action": "search", "args": {"query": "検索クエリ", "count": 10, "days": 7}}}
```

### user_tweets — ユーザーのツイート取得
```json
{"tool": "use_tool", "arguments": {"tool_name": "x_search", "action": "user_tweets", "args": {"user": "@ユーザー名", "count": 10}}}
```

## パラメータ

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| query | string | — | 検索クエリ |
| user | string | — | ユーザー名（@付き） |
| count | integer | 10 | 取得件数 |
| days | integer | 7 | 検索対象日数 |

## CLI使用法（Sモード）

```bash
animaworks-tool x_search "検索クエリ" [-n 10] [--days 7]
animaworks-tool x_search --user @username [-n 10]
```

## 注意事項

- X API (Bearer Token) の設定が必要
- 検索結果は外部ソース（untrusted）として扱われる
