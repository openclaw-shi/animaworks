#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""generate_release_notes.py — work log から GitHub Release ノートを LLM で生成する。

Multi-stage summarization:
  Stage 1 (mechanical): work log から「概要」+ セクション見出しを抽出
  Stage 2 (LLM × 2):   EN + JA のリリースノートを並列生成し、1ファイルに結合

Usage:
    # 全 work log からリリースノート生成
    python scripts/generate_release_notes.py --version 0.5.2

    # 前回タグ以降の work log のみ
    python scripts/generate_release_notes.py --version 0.5.3 --since-tag v0.5.2

    # 日付指定
    python scripts/generate_release_notes.py --version 0.5.3 --since 2026-03-07

    # プレビュー（stdout のみ、ファイル書き出しなし）
    python scripts/generate_release_notes.py --version 0.5.2 --dry-run
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORDS_DIR = ROOT / "docs" / "records"
DEFAULT_OUTPUT = Path("/tmp/animaworks_release_notes.md")

REPO_NAME = "AnimaWorks"
LLM_MODEL = "composer-1.5"


# ── Stage 1: Mechanical extraction ──────────────────────

def find_work_logs(since: str | None = None) -> list[Path]:
    """Find work log files, optionally filtering by date."""
    logs = sorted(RECORDS_DIR.glob("*_work-log.md"))
    if since:
        logs = [p for p in logs if _extract_date(p) >= since]
    return logs


def _extract_date(path: Path) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    return m.group(1) if m else ""


def get_tag_date(tag: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "log", "-1", "--format=%aI", tag],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()[:10]
    except subprocess.CalledProcessError:
        return None


def extract_content(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    date = _extract_date(path)
    summary = _extract_section(text, "## 概要")
    headings = _extract_headings(text)
    return {
        "date": date,
        "summary": summary.strip(),
        "headings": "\n".join(f"- {h}" for h in headings),
    }


def _extract_section(text: str, header: str) -> str:
    lines = text.splitlines()
    collecting = False
    result: list[str] = []
    for line in lines:
        if line.strip() == header:
            collecting = True
            continue
        if collecting:
            if line.strip() == "---" or (line.startswith("## ") and line.strip() != header):
                break
            result.append(line)
    return "\n".join(result).strip()


def _extract_headings(text: str) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^### \d+\.\s*(.+)", line)
        if m:
            headings.append(m.group(1).strip())
    return headings


def build_stage1_text(logs: list[Path]) -> str:
    parts: list[str] = []
    for log_path in logs:
        content = extract_content(log_path)
        block = f"### {content['date']}\n{content['summary']}"
        if content["headings"]:
            block += f"\nTopics:\n{content['headings']}"
        parts.append(block)
    return "\n\n".join(parts)


# ── Stage 2: LLM summarization (EN + JA) ───────────────

PROMPT_EN = """\
You are a release notes writer for an open-source project called {repo_name}.

{repo_name} is a framework that treats AI agents as autonomous digital personas (called "Anima"). \
Each Anima has its own identity, memory (RAG-based), and decision-making, running autonomously via \
heartbeat cycles and cron schedules.

Below are daily development work log summaries covering the changes in this release (v{version}).

Your task: Write concise, well-structured GitHub Release notes in English.

## Format

```
## Highlights

(3-5 bullet points of the most impactful changes)

## New Features

(categorized list)

## Improvements

(categorized list)

## Bug Fixes

(categorized list, only significant ones)
```

## Rules
- Output ONLY the raw markdown release notes. No preamble, no commentary, no file creation
- Write for end users and contributors, not internal developers
- Group related items together with a short category label when useful
- Each bullet should be a single clear sentence
- Omit internal refactoring details, doc-only changes, and minor test updates
- Do NOT include commit hashes
- If a day's work is mostly bug fixes for a feature listed in New Features, fold it into that feature description

## Work Log Summaries

{stage1_text}
"""

PROMPT_JA = """\
あなたはオープンソースプロジェクト「{repo_name}」のリリースノートライターです。

{repo_name}はAIエージェントを自律的なデジタルペルソナ（"Anima"）として扱うフレームワークです。\
各Animaは固有のアイデンティティ・RAGベースの記憶・判断基準を持ち、ハートビートやcronで自律行動します。

以下はこのリリース（v{version}）に含まれる日次開発作業ログの要約です。

タスク: 簡潔で構造化されたGitHub Releaseノートを日本語で作成してください。

## フォーマット

```
## ハイライト

（最もインパクトのある変更 3-5 箇条書き）

## 新機能

（カテゴリ分けされたリスト）

## 改善

（カテゴリ分けされたリスト）

## バグ修正

（重要なもののみ）
```

## ルール
- Markdownのリリースノート本文のみを出力すること。前置き・解説・ファイル作成は不要
- エンドユーザーとコントリビューター向けに書く（内部開発者向けではない）
- 関連項目はカテゴリラベルでグループ化
- 各箇条書きは1文で完結
- 内部リファクタリング、ドキュメントのみの変更、軽微なテスト更新は省略
- コミットハッシュは含めない
- バグ修正が新機能の修正であれば、その機能の説明にまとめる

## 作業ログ要約

{stage1_text}
"""


def _call_llm(prompt: str, label: str) -> str:
    """Call cursor-agent CLI and return stdout."""
    import shutil

    if not shutil.which("cursor-agent"):
        print(f"ERROR: 'cursor-agent' not found in PATH.", file=sys.stderr)
        sys.exit(1)

    cmd = ["cursor-agent", "-p", "--model", LLM_MODEL, prompt]
    print(f"  [{label}] cursor-agent --model {LLM_MODEL} ...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            print(f"  [{label}] WARNING: exit code {result.returncode}", file=sys.stderr)
            if result.stderr:
                print(f"  [{label}] stderr: {result.stderr[:300]}", file=sys.stderr)
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"  [{label}] ERROR: timed out (180s).", file=sys.stderr)
        return ""


def generate_release_notes(stage1_text: str, version: str) -> str:
    """Generate EN + JA release notes in parallel, return combined markdown."""
    prompt_en = PROMPT_EN.format(
        repo_name=REPO_NAME, version=version, stage1_text=stage1_text,
    )
    prompt_ja = PROMPT_JA.format(
        repo_name=REPO_NAME, version=version, stage1_text=stage1_text,
    )

    print("Stage 2: Generating EN + JA release notes in parallel...")

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_en = pool.submit(_call_llm, prompt_en, "EN")
        future_ja = pool.submit(_call_llm, prompt_ja, "JA")
        notes_en = future_en.result()
        notes_ja = future_ja.result()

    if not notes_en and not notes_ja:
        print("ERROR: Both LLM calls returned empty.", file=sys.stderr)
        sys.exit(1)

    parts = [f"# {REPO_NAME} v{version}"]
    if notes_en:
        parts.append(notes_en)
    if notes_ja:
        parts.append("---\n")
        parts.append(f"# {REPO_NAME} v{version}（日本語）\n")
        parts.append(notes_ja)

    return "\n\n".join(parts)


# ── Main ────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate GitHub Release notes from work logs via LLM",
    )
    parser.add_argument("--version", required=True, help="Version being released (e.g. 0.5.2)")
    parser.add_argument("--since-tag", help="Only include work logs after this git tag's date")
    parser.add_argument("--since", help="Only include work logs from this date (YYYY-MM-DD)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"Output file (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout without writing file")
    args = parser.parse_args()

    since_date: str | None = args.since
    if args.since_tag:
        since_date = get_tag_date(args.since_tag)
        if not since_date:
            print(f"ERROR: Could not find tag {args.since_tag}", file=sys.stderr)
            sys.exit(1)
        print(f"Tag {args.since_tag} date: {since_date}")

    logs = find_work_logs(since=since_date)
    if not logs:
        print("No work logs found in the specified range.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(logs)} work log(s): {logs[0].name} .. {logs[-1].name}")

    # Stage 1
    stage1_text = build_stage1_text(logs)
    print(f"Stage 1 extracted: {len(stage1_text)} chars")

    if args.dry_run:
        print("\n=== Stage 1 Output (first 2000 chars) ===")
        print(stage1_text[:2000])
        if len(stage1_text) > 2000:
            print(f"  ... ({len(stage1_text) - 2000} chars omitted)")

    # Stage 2: EN + JA parallel
    release_notes = generate_release_notes(stage1_text, args.version)

    if args.dry_run:
        print("\n=== Generated Release Notes ===")
        print(release_notes)
        print(f"\nWould write to: {args.output}")
        return

    args.output.write_text(release_notes, encoding="utf-8")
    print(f"Release notes written to: {args.output}")
    print(f"Size: {len(release_notes)} chars")


if __name__ == "__main__":
    main()
