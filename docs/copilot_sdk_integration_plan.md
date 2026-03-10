# GitHub Copilot SDK 統合計画書（AnimaWorks）

## 1. 目的

本計画書は、AnimaWorks に GitHub Copilot SDK を安全かつ段階的に導入し、
あわせて**初期セットアップ画面から選択可能**にするための実装計画をまとめたものです。

対象は以下を一体で扱います。

- 実行モード拡張（Mode P: Copilot）
- Executor 実装と登録
- モデル/モード解決ロジック拡張
- 初期セットアップ（Web UI + API）導線追加
- 周辺機能（CLI表示、アイドル圧縮、i18n、ドキュメント）追従
- 検証・ロールアウト計画

---

## 2. 背景と現状

- 既存の実行モードは S/A/B/C を中心に構成されており、Copilot 専用モードは未実装。
- Mode C（Codex SDK）は、追加モード実装の最新テンプレートとして構造が整っている。
- 初期セットアップでは provider を選択できるが、選択内容が anima の model 設定まで一貫して保存されていない。

---

## 3. 方針

### 3.1 推奨アーキテクチャ

**Mode P を新設**し、Copilot SDK 用 Executor を独立実装する。

理由:

- セッション継続・イベント処理・ツール連携などの責務を Mode A（LiteLLM）と明確に分離できる。
- 将来の SDK 差分吸収（Copilot CLI 仕様変更、認証方式追加）を局所化できる。
- Mode C と同様の運用（SDK存在チェック→フォールバック）で統一できる。

### 3.2 代替方針（暫定）

Copilot API が OpenAI 互換として十分運用できる場合は、短期的には Mode A + `base_url` 構成で接続可能。
ただし本計画書では、長期運用性を優先し Mode P 新設を主計画とする。

---

## 4. 変更対象（実装スコープ）

### 4.1 依存関係

#### `pyproject.toml`

- optional dependency に `copilot = ["github-copilot-sdk>=..."]` を追加。
- `all-tools` に `copilot` を連結。
- 既存の `codex` 追加方式に合わせる。

---

### 4.2 実行エンジン層

#### 新規: `core/execution/copilot_sdk.py`

`CodexSDKExecutor` を参考に `CopilotSDKExecutor` を実装。

実装要件:

1. `BaseExecutor` 継承
2. `execute()` 実装
3. `execute_streaming()` 実装
4. SDK import 可否関数（例: `is_copilot_sdk_available()`）
5. モデル名正規化（例: `copilot/gpt-5` → `gpt-5`）
6. session/thread ID の保存・再開
7. イベント→`ExecutionResult` 変換
8. `ToolCallRecord` / `TokenUsage` へのマッピング
9. 異常時は `StreamDisconnectedError` 等の既存契約に準拠

#### `core/execution/__init__.py`

- `ImportError` フォールバック付きで `CopilotSDKExecutor` を登録。
- `__all__` に追記。

#### `core/_agent_executor.py`

- `_create_executor()` に `mode == "p"` 分岐を追加。
- SDK未導入時は `LiteLLMExecutor`（Mode A相当）へフォールバック。
- フォールバック時の model remap 方針を規定（`copilot/*` → `openai/*` など）。

---

### 4.3 モード解決・モデル定義

#### `core/config/models.py`

- `DEFAULT_MODEL_MODE_PATTERNS` に `"copilot/*": "P"` を追加。
- `_normalise_mode()` の許容値に `"P"` を追加。
- `resolve_execution_mode()` の docstring/戻り値説明を S/A/B/C/P 対応に更新。
- 必要であれば `KNOWN_MODELS` / `RECOMMENDED_MODELS` に Copilot 系候補を追加。

---

### 4.4 初期セットアップ導線（Web UI/API）

#### `server/static/setup/steps/environment.js`

- `PROVIDERS` に `copilot` を追加。
- provider 選択時の入力要件（APIキー/トークン）を定義。
- バリデーション文言を整理：
  - provider 未選択 → `error.provider_required`
  - key 必須なのに未入力 → `error.apikey_required`

#### `server/routes/setup.py`

- `AVAILABLE_PROVIDERS` に `copilot` を追加。
- `/validate-key` に copilot 分岐を追加（認証方式に応じて最小検証）。
- `SetupCompleteRequest` を拡張し、`model`（必要なら `execution_mode`）を受け取れるようにする。
- `complete_setup()` で `config.animas[anima_name].model` を保存。

#### `server/static/setup/steps/confirm.js`

- 完了 payload に `model`（必要なら `execution_mode`）を追加。
- 確認画面サマリーに provider だけでなく model/mode も表示。

#### i18n (`server/static/setup/i18n/*.json`)

- `env.provider.copilot`, `env.provider.copilot.desc` を追加。
- 文言追加は全ロケール反映を推奨（最低限 `en`, `ja`）。

---

### 4.5 周辺機能の漏れ対策（必須）

#### `core/session_compactor.py`

- `mode == "p"` 分岐を追加。
- 圧縮手法は Copilot session 構造に合わせる（暫定的に C 相当でも可）。

#### CLI表示

- `cli/commands/models_cmd.py` の `_MODE_LABELS` に `P` を追加。
- `cli/commands/anima_mgmt.py` の mode 表示辞書にも `P` を追加。

#### 初期化/デフォルト

- `core/init.py` の `model_modes` 初期コピーに P パターンが含まれることを確認。

---

## 5. 実装順序（推奨）

1. **Mode 解決基盤**（models.py）
2. **Executor 本体**（copilot_sdk.py）
3. **Executor 登録/Factory**（`__init__`, `_agent_executor.py`）
4. **セットアップ API/UI**（setup.py, environment.js, confirm.js, i18n）
5. **周辺追従**（session_compactor, CLI 表示, docs）
6. **テスト追加・回帰確認**

この順序で進めることで、途中段階でもバックエンド単体確認→UI接続確認が段階的に可能。

---

## 6. テスト計画

### 6.1 単体テスト

1. `resolve_execution_mode("copilot/..." ) == "P"`
2. `_normalise_mode("p") == "P"`
3. SDK 未導入時、`mode=p` で LiteLLM フォールバックされる
4. setup payload の `model` が config へ保存される
5. provider 未選択時に正しいエラー文言が返る

### 6.2 結合テスト

1. Setup UI で Copilot を選択して完了できる
2. 生成 anima が `copilot/*` モデルを持つ
3. 実行時に Mode P executor が選択される
4. streaming 実行で `text_delta` → `done` が成立

### 6.3 回帰テスト

1. S/C/A/B の既存動作が維持される
2. session compactor が P 追加後も他モードで退行しない
3. CLI `models list` / anima 詳細表示が崩れない

---

## 7. ロールアウト計画

### Phase 1（内部有効化）

- Mode P を実装するが、既定モデルは変更しない。
- Setup 上で Copilot は「任意選択」として提供。

### Phase 2（安定化）

- 実運用での認証/再接続/セッション再開のログを監視。
- 既知エラーを集約し、再試行ポリシーを調整。

### Phase 3（拡張）

- Copilot 固有機能（モデル一覧同期、BYOK補助UI、詳細トークン統計）を追加。

---

## 8. リスクと対策

1. **Copilot SDK/CLI の仕様変更**
   - 対策: executor で SDK API 依存点を局所化。例外は明示ログ。

2. **認証方式の差異（GitHub token / BYOK）**
   - 対策: 初期実装は 1方式に限定し、後方拡張可能な設定スキーマにする。

3. **Setup と実行設定の不整合**
   - 対策: setup payload で provider/model を同時保存し、confirm 画面で明示確認。

4. **モード追加漏れ（表示系・補助処理）**
   - 対策: `mode` 文字列比較箇所を横断チェックし、P対応チェックリストを CI に組み込む。

---

## 9. 完了条件（Definition of Done）

- [ ] `copilot/*` モデルで Mode P が自動解決される
- [ ] Copilot SDK executor が通常/streaming 実行できる
- [ ] SDK 未導入時に安全フォールバックする
- [ ] 初期セットアップで Copilot を選択できる
- [ ] Setup 完了時に anima model が保存される
- [ ] session compactor / CLI 表示が P 対応済み
- [ ] i18n 追加キーで表示崩れがない
- [ ] テスト（単体・結合・回帰）を通過

---

## 10. 変更チェックリスト（実装者向け）

- [ ] `pyproject.toml`
- [ ] `core/execution/copilot_sdk.py`（新規）
- [ ] `core/execution/__init__.py`
- [ ] `core/_agent_executor.py`
- [ ] `core/config/models.py`
- [ ] `core/session_compactor.py`
- [ ] `cli/commands/models_cmd.py`
- [ ] `cli/commands/anima_mgmt.py`
- [ ] `server/routes/setup.py`
- [ ] `server/static/setup/steps/environment.js`
- [ ] `server/static/setup/steps/confirm.js`
- [ ] `server/static/setup/i18n/*.json`
- [ ] 関連テスト追加/更新

