---
name: github-tool
description: >-
  GitHub連携ツール。Issue・PR一覧取得、Issue作成、PR作成。gh CLIラッパー。
  「GitHub」「Issue」「PR」「プルリクエスト」「リポジトリ」
tags: [development, github, external]
---

# GitHub ツール

GitHubのIssue・PRをgh CLI経由で操作する外部ツール。

## use_tool での呼び出し

```json
{"tool": "use_tool", "arguments": {"tool_name": "github", "action": "ACTION", "args": {...}}}
```

## アクション一覧

### list_issues — Issue一覧
```json
{"tool_name": "github", "action": "list_issues", "args": {"repo": "owner/repo", "state": "open", "limit": 20}}
```

### create_issue — Issue作成
```json
{"tool_name": "github", "action": "create_issue", "args": {"title": "タイトル", "body": "本文", "labels": "bug,enhancement"}}
```

### list_prs — PR一覧
```json
{"tool_name": "github", "action": "list_prs", "args": {"repo": "owner/repo", "state": "open", "limit": 20}}
```

### create_pr — PR作成
```json
{"tool_name": "github", "action": "create_pr", "args": {"title": "タイトル", "body": "本文", "head": "feature-branch", "base": "main"}}
```

## CLI使用法（Sモード）

```bash
animaworks-tool github issues [--repo OWNER/REPO] [--state open] [--limit 20]
animaworks-tool github create-issue --title TITLE --body BODY [--labels LABELS]
animaworks-tool github prs [--repo OWNER/REPO] [--state open] [--limit 20]
animaworks-tool github create-pr --title TITLE --body BODY --head BRANCH [--base main]
```

## 注意事項

- gh CLI がインストール済みで認証済みであること
- --repo 省略時はカレントディレクトリのリポジトリを使用
