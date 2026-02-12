# Config: Sakura

## モデル設定

- model: claude-sonnet-4-20250514
- fallback_model: claude-haiku-4-20250414
- max_tokens: 4096
- max_turns: 20

## API接続

- api_key_env: ANTHROPIC_API_KEY
- api_base_url:

## 備考

api_key_env には環境変数名を指定する（キー自体は書かない）。
未設定の場合はデフォルトの ANTHROPIC_API_KEY を使用する。

api_base_url はLLMのエンドポイントURL。
空欄の場合はAnthropicのデフォルト（https://api.anthropic.com）を使用する。

### 設定例

Anthropic（デフォルト）:
- api_key_env: ANTHROPIC_API_KEY
- api_base_url:

Ollama（ローカル）:
- model: gemma3:27b
- api_key_env: OLLAMA_API_KEY
- api_base_url: http://localhost:11434/v1

別のAnthropicキー:
- api_key_env: ANTHROPIC_API_KEY_SAKURA
- api_base_url:
