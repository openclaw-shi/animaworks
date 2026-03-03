---
name: transcribe-tool
description: >-
  Audio transcription tool. Convert audio files to text using Whisper models.
  "transcribe" "speech to text" "whisper" "STT" "audio"
tags: [audio, transcription, whisper, external]
---

# Transcribe Tool

External tool for speech-to-text using Whisper (faster-whisper).

## Invocation via use_tool

### audio — Transcribe audio file
```json
{"tool": "use_tool", "arguments": {"tool_name": "transcribe", "action": "audio", "args": {"audio_path": "audio file path", "language": "ja"}}}
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|--------------|
| audio_path | string | (required) | Path to audio file |
| language | string | null | Language code (ja, en, etc.). null for auto-detect |
| model | string | "large-v3-turbo" | Whisper model name |
| raw | boolean | false | If true, skip LLM post-processing |

## CLI Usage (S-mode)

```bash
animaworks-tool transcribe transcribe audio_file.wav [-l ja] [-m large-v3-turbo]
```

## Notes

- faster-whisper must be installed
- CUDA-compatible ctranslate2 required for GPU acceleration
- Model is auto-downloaded on first run
