---
name: web-search-tool
description: >-
  Web検索ツール。Brave Search APIを使用してインターネットを検索する。
  「検索」「ウェブ検索」「Web検索」「調べる」「ググる」「Brave」
tags: [search, web, external]
---

# Web Search ツール

Brave Search APIを使ったWeb検索外部ツール。

## use_tool での呼び出し

```json
{"tool": "use_tool", "arguments": {"tool_name": "web_search", "action": "search", "args": {"query": "検索クエリ", "count": 10}}}
```

## パラメータ

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| query | string | (必須) | 検索クエリ |
| count | integer | 10 | 取得件数 |
| lang | string | "ja" | 検索言語 |
| freshness | string | null | 鮮度フィルタ (pd=24h, pw=1週間, pm=1ヶ月, py=1年) |

## CLI使用法（Sモード）

```bash
animaworks-tool web_search "検索クエリ" [-n 10] [-l ja] [-f pd]
```

## 注意事項

- BRAVE_API_KEY の設定が必要
- 検索結果は外部ソース（untrusted）として扱われる
