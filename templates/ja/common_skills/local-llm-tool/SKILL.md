---
name: local-llm-tool
description: >-
  ローカルLLM実行ツール。Ollama/vLLM経由でローカルモデルにテキスト生成・チャットを依頼。
  「ローカルLLM」「Ollama」「テキスト生成」「ローカルモデル」
tags: [llm, local, ollama, external]
---

# Local LLM ツール

ローカルLLM（Ollama/vLLM）経由でテキスト生成・チャットを行う外部ツール。

## use_tool での呼び出し

```json
{"tool": "use_tool", "arguments": {"tool_name": "local_llm", "action": "ACTION", "args": {...}}}
```

## アクション一覧

### generate — テキスト生成
```json
{"tool_name": "local_llm", "action": "generate", "args": {"prompt": "プロンプト", "system": "システムプロンプト(任意)", "temperature": 0.7, "max_tokens": 2048}}
```

### chat — チャット（複数ターン）
```json
{"tool_name": "local_llm", "action": "chat", "args": {"messages": [{"role": "user", "content": "質問"}], "system": "システムプロンプト(任意)"}}
```

### models — モデル一覧
```json
{"tool_name": "local_llm", "action": "models", "args": {}}
```

### status — サーバー状態確認
```json
{"tool_name": "local_llm", "action": "status", "args": {}}
```

## CLI使用法（Sモード）

```bash
animaworks-tool local_llm generate "プロンプト" [-S "システムプロンプト"]
animaworks-tool local_llm list
animaworks-tool local_llm status
```

## 注意事項

- Ollamaサーバーまたは vLLM サーバーが起動していること
- -s/--server でサーバーURL指定可能
- -m/--model でモデル指定可能
