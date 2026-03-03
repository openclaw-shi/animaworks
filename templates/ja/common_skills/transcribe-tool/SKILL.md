---
name: transcribe-tool
description: >-
  音声文字起こしツール。Whisperモデルで音声ファイルをテキストに変換。LLM後処理オプション付き。
  「文字起こし」「transcribe」「音声認識」「Whisper」「STT」
tags: [audio, transcription, whisper, external]
---

# Transcribe ツール

Whisper (faster-whisper) を使った音声文字起こしツール。

## use_tool での呼び出し

### audio — 音声文字起こし
```json
{"tool": "use_tool", "arguments": {"tool_name": "transcribe", "action": "audio", "args": {"audio_path": "音声ファイルパス", "language": "ja"}}}
```

## パラメータ

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| audio_path | string | (必須) | 音声ファイルのパス |
| language | string | null | 言語コード (ja, en 等)。null で自動検出 |
| model | string | "large-v3-turbo" | Whisperモデル名 |
| raw | boolean | false | true の場合、LLM後処理をスキップ |

## CLI使用法（Sモード）

```bash
animaworks-tool transcribe transcribe audio_file.wav [-l ja] [-m large-v3-turbo]
```

## 注意事項

- faster-whisper のインストールが必要
- GPU使用時はCUDA対応の ctranslate2 が必要
- 初回実行時にモデルが自動ダウンロードされる
