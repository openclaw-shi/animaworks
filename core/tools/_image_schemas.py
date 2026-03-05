# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0
#
# This file is part of AnimaWorks core/server, licensed under Apache-2.0.
# See LICENSE for the full license text.

"""Tool schemas and CLI guide for image generation."""

from __future__ import annotations

__all__ = [
    "get_tool_schemas",
    "get_cli_guide",
]


def get_tool_schemas() -> list[dict]:
    """Return Anthropic tool_use schemas for image generation tools."""
    return []


def get_cli_guide() -> str:
    """Return CLI usage guide for image generation tools."""
    return """\
### 画像・3Dモデル生成 (image_gen)

Aモードのツール名: `generate_character_assets` / `generate_fullbody` / `generate_bustup` 等

```bash
# 全6ステップ一括生成（推奨）
animaworks-tool image_gen pipeline "1girl, black hair, ..." --negative "lowres, bad anatomy, ..." --anima-dir <anima_dir> -j

# 個別ステップ
animaworks-tool image_gen fullbody "prompt" --anima-dir <anima_dir> -j
animaworks-tool image_gen bustup --anima-dir <anima_dir> -j
animaworks-tool image_gen chibi --anima-dir <anima_dir> -j
animaworks-tool image_gen 3d --anima-dir <anima_dir> -j
animaworks-tool image_gen rigging <model.glb> -o <output_dir> -j
animaworks-tool image_gen animations <model.glb> -o <output_dir> -j
```"""
