#!/usr/bin/env python3
"""Analyze heartbeat session output tokens and correlate with actual task creation.

Analyzes:
- Token usage: output_tokens per heartbeat session (last 12h)
- State files: current_task.md, pending/, task_queue
- Tasks created by heartbeats in past 12h
- Assessment: are output tokens justified by task creation?

Usage:
  python scripts/analyze_heartbeat_output.py [--hours 12]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
ANIMAWORKS = Path(os.environ.get("ANIMAWORKS_HOME", str(Path.home() / ".animaworks")))
ANIMAS_DIR = Path(ANIMAWORKS) / "animas"
OUTPUT_TOKEN_THRESHOLD = 5000  # Flag animas exceeding this per session


def parse_ts(ts: str) -> datetime | None:
    """Parse ISO8601 timestamp to datetime."""
    try:
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze heartbeat output tokens")
    parser.add_argument("--hours", type=int, default=12, help="Look back hours")
    parser.add_argument("--threshold", type=int, default=OUTPUT_TOKEN_THRESHOLD)
    args = parser.parse_args()

    cutoff = datetime.now(JST) - timedelta(hours=args.hours)
    cutoff_str = cutoff.isoformat()

    print("=" * 70)
    print("HEARTBEAT OUTPUT TOKEN ANALYSIS")
    print(f"Cutoff: {cutoff_str} (past {args.hours}h)")
    print(f"Threshold for high output: >{args.threshold} tokens/session")
    print("=" * 70)

    anima_dirs = sorted(
        d for d in ANIMAS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("tmp") and d.name != "test"
    )

    # 1. Token usage: heartbeat output_tokens
    heartbeat_tokens: dict[str, list[dict]] = defaultdict(list)
    high_output_animas: list[tuple[str, int, int]] = []

    for anima_dir in anima_dirs:
        name = anima_dir.name
        token_dir = anima_dir / "token_usage"
        if not token_dir.exists():
            continue

        today = datetime.now(JST).date()
        yesterday = today - timedelta(days=1)
        for date_file in [f"{yesterday}.jsonl", f"{today}.jsonl"]:
            path = token_dir / date_file
            if not path.exists():
                continue
            try:
                for line in path.read_text(encoding="utf-8").strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("trigger") != "heartbeat":
                        continue
                    ts = entry.get("ts")
                    if not ts:
                        continue
                    dt = parse_ts(ts)
                    if dt and dt >= cutoff:
                        out = entry.get("output_tokens", 0)
                        heartbeat_tokens[name].append({
                            "ts": ts,
                            "output_tokens": out,
                            "input_tokens": entry.get("input_tokens", 0),
                            "turns": entry.get("turns", 0),
                            "duration_ms": entry.get("duration_ms", 0),
                        })
            except Exception as e:
                print(f"  [WARN] {name} token_usage: {e}", file=sys.stderr)

    print("\n## 1. OUTPUT TOKEN DISTRIBUTION (heartbeat sessions, past 12h)")
    print("-" * 70)

    for name in sorted(heartbeat_tokens.keys()):
        sessions = heartbeat_tokens[name]
        if not sessions:
            continue
        total_out = sum(s["output_tokens"] for s in sessions)
        avg_out = total_out / len(sessions)
        max_out = max(s["output_tokens"] for s in sessions)
        flag = " [HIGH]" if max_out > args.threshold else ""
        print(f"  {name:12} sessions={len(sessions):2}  total_out={total_out:6}  avg={avg_out:.0f}  max={max_out:6}{flag}")
        if max_out > args.threshold:
            high_output_animas.append((name, total_out, len(sessions)))
        for s in sessions[:3]:
            print(f"    - {s['ts'][11:19]}  out={s['output_tokens']:5}  turns={s['turns']}")

    # 2. State files
    print("\n## 2. STATE FILES (current_task.md, pending/, task_queue)")
    print("-" * 70)

    state_summaries: dict[str, dict] = {}

    for anima_dir in anima_dirs:
        name = anima_dir.name
        state_dir = anima_dir / "state"
        if not state_dir.exists():
            continue

        summary: dict = {"current_task": "", "pending_files": [], "heartbeat_tasks_12h": 0}

        ct_path = state_dir / "current_task.md"
        if ct_path.exists():
            mtime = datetime.fromtimestamp(ct_path.stat().st_mtime, tz=JST)
            content = ct_path.read_text(encoding="utf-8").strip()
            summary["current_task"] = f"mtime={mtime.strftime('%Y-%m-%d %H:%M')}  "
            summary["current_task"] += content[:120] + "..." if len(content) > 120 else content

        pending_dir = state_dir / "pending"
        if pending_dir.exists():
            for f in pending_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=JST)
                    if mtime >= cutoff:
                        summary["pending_files"].append((f.name, mtime.strftime("%Y-%m-%d %H:%M")))

        bg_pending = state_dir / "background_tasks" / "pending"
        if bg_pending.exists():
            for f in bg_pending.iterdir():
                if f.suffix == ".json":
                    mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=JST)
                    if mtime >= cutoff:
                        summary["pending_files"].append((f"bg/{f.name}", mtime.strftime("%Y-%m-%d %H:%M")))

        state_summaries[name] = summary

    for name in sorted(state_summaries.keys()):
        s = state_summaries[name]
        if not s["current_task"] and not s["pending_files"] and s["heartbeat_tasks_12h"] == 0:
            if name not in heartbeat_tokens:
                continue
        print(f"\n  {name}:")
        if s["current_task"]:
            print(f"    current_task.md: {s['current_task'][:100]}...")
        if s["pending_files"]:
            for fn, mt in s["pending_files"]:
                print(f"    pending (12h): {fn} @ {mt}")
        if not s["current_task"] and not s["pending_files"] and s["heartbeat_tasks_12h"] == 0 and name in heartbeat_tokens:
            print(f"    (no state changes in 12h)")

    # 3. Pending files created in last 12h
    print("\n## 3. PENDING FILES CREATED IN LAST 12h")
    print("-" * 70)

    any_pending = False
    for anima_dir in anima_dirs:
        name = anima_dir.name
        for subdir, label in [
            (anima_dir / "state" / "pending", "state/pending"),
            (anima_dir / "state" / "background_tasks" / "pending", "background_tasks/pending"),
        ]:
            if not subdir.exists():
                continue
            for f in subdir.iterdir():
                if f.is_file() and (f.suffix in (".json", ".md") or not f.name.startswith(".")):
                    mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=JST)
                    if mtime >= cutoff:
                        any_pending = True
                        print(f"  {name}/{label}/{f.name}  @ {mtime.strftime('%Y-%m-%d %H:%M')}")
    if not any_pending:
        print("  (none)")

    # 4. Assessment
    print("\n## 4. ASSESSMENT: Are output tokens justified by task creation?")
    print("-" * 70)

    total_heartbeat_sessions = sum(len(s) for s in heartbeat_tokens.values())
    pending_count = 0
    for anima_dir in anima_dirs:
        for subdir in [
            anima_dir / "state" / "pending",
            anima_dir / "state" / "background_tasks" / "pending",
        ]:
            if subdir.exists():
                for f in subdir.iterdir():
                    if f.is_file() and f.suffix in (".json", ".md"):
                        if datetime.fromtimestamp(f.stat().st_mtime, tz=JST) >= cutoff:
                            pending_count += 1

    print(f"  Total heartbeat sessions (12h): {total_heartbeat_sessions}")
    print(f"  Pending files created (12h):     {pending_count}")
    if total_heartbeat_sessions:
        print(f"  Ratio (tasks/sessions):           {pending_count / total_heartbeat_sessions:.2f}")
    else:
        print("  Ratio: N/A")

    if high_output_animas:
        print("\n  Animas with high output tokens (>{} per session):".format(args.threshold))
        for name, total, sessions in sorted(high_output_animas, key=lambda x: -x[1]):
            pending_for = len(state_summaries.get(name, {}).get("pending_files", []))
            verdict = "justified" if pending_for > 0 else "LOW YIELD (no tasks created)"
            print(f"    - {name}: {total} tokens in {sessions} sessions, {pending_for} pending files -> {verdict}")
    else:
        print("\n  No animas exceeded the output token threshold.")

    print("\n" + "=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
