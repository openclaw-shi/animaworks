---
name: image-gen-tool
description: >-
  画像・3Dモデル生成ツール。キャラクター立ち絵・バストアップ・ちびキャラ・3Dモデル生成。
  NovelAI/Flux/Meshy対応。
  「画像生成」「立ち絵」「バストアップ」「ちびキャラ」「3Dモデル」「アバター」
tags: [image, 3d, generation, external]
---

# Image Gen ツール

キャラクター画像・3Dモデルを生成する外部ツール。

## use_tool での呼び出し

```json
{"tool": "use_tool", "arguments": {"tool_name": "image_gen", "action": "ACTION", "args": {...}}}
```

## アクション一覧

### character_assets — パイプライン一括生成
```json
{"tool_name": "image_gen", "action": "character_assets", "args": {"prompt": "1girl, ...", "anima_dir": "$ANIMAWORKS_ANIMA_DIR"}}
```

### fullbody — 全身立ち絵
```json
{"tool_name": "image_gen", "action": "fullbody", "args": {"prompt": "1girl, standing, ...", "width": 832, "height": 1216}}
```

### bustup — バストアップ
```json
{"tool_name": "image_gen", "action": "bustup", "args": {"reference": "元画像パス", "prompt": "追加プロンプト(任意)"}}
```

### chibi — ちびキャラ
```json
{"tool_name": "image_gen", "action": "chibi", "args": {"reference": "元画像パス", "prompt": "追加プロンプト(任意)"}}
```

### 3d_model — 3Dモデル生成
```json
{"tool_name": "image_gen", "action": "3d_model", "args": {"image": "画像パス"}}
```

## CLI使用法（Sモード）

```bash
animaworks-tool image_gen pipeline "1girl, ..." --anima-dir $ANIMAWORKS_ANIMA_DIR
animaworks-tool image_gen fullbody "1girl, standing, ..."
animaworks-tool image_gen bustup reference.png
animaworks-tool image_gen chibi reference.png
animaworks-tool image_gen 3d image.png
```

## 注意事項

- 長時間処理のため `animaworks-tool submit image_gen pipeline ...` でバックグラウンド実行推奨
- NovelAI APIキーまたはfal.ai APIキーが必要
- 3D生成にはMeshy APIキーが必要
