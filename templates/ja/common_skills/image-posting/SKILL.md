---
name: image-posting
description: >-
  チャット応答に画像を添付・表示するスキル。
  ツール結果(web_search等)に含まれる画像URLの自動検出・プロキシ経由表示の仕組み、
  応答テキスト内でのMarkdown画像構文による埋め込み方法、
  自分のassets画像の表示方法を提供する。
  「画像を貼る」「画像を見せて」「イラスト表示」「画像添付」「写真を貼って」「検索画像を表示」
---

# image-posting — チャット応答への画像表示

## 概要

チャット応答に画像を含める仕組みは2系統ある:

1. **ツール結果からの自動抽出** — ツール結果に画像URLやパスが含まれると、フレームワークが自動検出してチャットバブルに表示する
2. **Markdown画像構文** — 応答テキスト内に `![alt](url)` を書くとフロントエンドがレンダリングする

## 方法1: ツール結果からの自動表示

ツール（web_search、image_gen等）を呼び出した結果に画像情報が含まれていれば、フレームワークが自動でチャットバブルに画像を表示する。Anima側で特別な操作は不要。

### 自動検出される条件

ツール結果のJSON内で以下が検出されると画像として扱われる:

- **パス検出**: `assets/` または `attachments/` で始まるパス → `source: generated`（信頼済み）
- **URL検出**: `https://` で始まり `.png` `.jpg` `.jpeg` `.gif` `.webp` で終わるURL → `source: searched`（プロキシ経由）
- **キー名検出**: `image_url`, `thumbnail`, `src`, `url` キーに画像URLがある場合も検出

1応答あたり最大5枚まで。

### searched画像のプロキシ制限

外部URL画像はセキュリティのためプロキシ経由で配信される。許可ドメイン:

- `cdn.search.brave.com`
- `images.unsplash.com`
- `images.pexels.com`
- `upload.wikimedia.org`

上記ドメイン外の画像URLはプロキシでブロックされる。

## 方法2: Markdown画像構文

応答テキスト内にMarkdown画像構文を直接書いて画像を表示する。

### 自分のアセット画像を見せる場合

```
![説明](/api/animas/{自分の名前}/assets/{ファイル名})
```

例:

```
これが私のアバターです！
![アバター](/api/animas/miyuki/assets/avatar_fullbody.png)
```

自分のアセット一覧は `list_files("assets/")` で確認できる。

### 添付画像を見せる場合

```
![説明](/api/animas/{自分の名前}/attachments/{ファイル名})
```

## 注意事項

- 他のAnimaのアセットパスは直接参照できない（権限外）
- 外部URLの直リンクは非推奨。プロキシ許可ドメインのみ表示可能
- 画像生成ツール（generate_fullbody等）の結果は自動表示されるため、Markdown構文は不要
- 1応答あたりの自動表示は最大5枚
