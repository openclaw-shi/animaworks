#!/usr/bin/env python3
"""Analyze heartbeat activity for AnimaWorks animas.

Lists each heartbeat session, actions taken, and classifies empty vs productive heartbeats.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Activity types that count as "productive" output
PRODUCTIVE_TYPES = frozenset({
    "message_sent",   # DM sent
    "channel_post",   # Posted to shared channel
    "memory_write",   # Wrote to memory
    "human_notify",   # Notified human
})

# Tool names that indicate task creation or meaningful output
TASK_CREATION_TOOLS = frozenset({"Edit", "Bash"})
TASK_CREATION_PATHS = ("pending", "task_queue", "current_task.md")


def parse_ts(ts_str: str) -> datetime:
    """Parse ISO8601 timestamp to datetime (timezone-aware)."""
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def is_task_creation(entry: dict) -> bool:
    """Check if tool_use indicates task creation."""
    if entry.get("type") != "tool_use":
        return False
    tool = entry.get("tool", "")
    if tool not in TASK_CREATION_TOOLS:
        return False
    content = entry.get("content", "")
    args = entry.get("meta", {}).get("args", {})
    paths = [content, args.get("file_path", ""), args.get("path", "")]
    for p in paths:
        if any(needle in str(p) for needle in TASK_CREATION_PATHS):
            return True
    return False


def analyze_anima(anima_dir: Path, cutoff: datetime) -> dict | None:
    """Analyze heartbeat sessions for one anima."""
    log_dir = anima_dir / "activity_log"
    if not log_dir.exists():
        return None

    entries: list[dict] = []
    for date_file in ["2026-03-04.jsonl", "2026-03-05.jsonl"]:
        path = log_dir / date_file
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    entries.sort(key=lambda e: parse_ts(e.get("ts", "1970-01-01")))

    sessions: list[dict] = []
    i = 0
    while i < len(entries):
        e = entries[i]
        if e.get("type") != "heartbeat_start":
            i += 1
            continue
        ts = parse_ts(e.get("ts", ""))
        if ts < cutoff:
            i += 1
            continue

        session = {
            "start_ts": ts,
            "end_ts": None,
            "start_idx": i,
            "end_idx": None,
            "actions": [],
            "productive_types": set(),
            "task_creation": False,
        }

        j = i + 1
        while j < len(entries):
            ev = entries[j]
            if ev.get("type") == "heartbeat_end":
                session["end_ts"] = parse_ts(ev.get("ts", ""))
                session["end_idx"] = j
                break
            if ev.get("type") in PRODUCTIVE_TYPES:
                session["productive_types"].add(ev["type"])
                session["actions"].append({
                    "type": ev["type"],
                    "ts": ev.get("ts"),
                    "summary": (ev.get("summary", "") or "")[:80],
                    "to": ev.get("to"),
                    "channel": ev.get("channel"),
                })
            elif ev.get("type") == "tool_use" and is_task_creation(ev):
                session["task_creation"] = True
                session["actions"].append({
                    "type": "task_creation",
                    "ts": ev.get("ts"),
                    "tool": ev.get("tool"),
                    "content": str(ev.get("content", ""))[:100],
                })
            j += 1

        if session["end_ts"] is not None:
            session["productive"] = (
                len(session["productive_types"]) > 0 or session["task_creation"]
            )
            sessions.append(session)

        i = j + 1 if session["end_ts"] else i + 1

    return {
        "name": anima_dir.name,
        "sessions": sessions,
        "total": len(sessions),
        "empty": sum(1 for s in sessions if not s["productive"]),
        "productive": sum(1 for s in sessions if s["productive"]),
        "all_actions": [a for s in sessions for a in s["actions"]],
    } if sessions else None


def main() -> None:
    base = Path.home() / ".animaworks" / "animas"
    if not base.exists():
        print("AnimaWorks data dir not found:", base)
        return

    now = datetime(2026, 3, 5, 14, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    cutoff = now - timedelta(hours=12)

    anima_dirs = [
        d for d in base.iterdir()
        if d.is_dir() and not d.name.startswith(("test", "tmp"))
    ]

    results: list[dict] = []
    for anima_dir in sorted(anima_dirs):
        r = analyze_anima(anima_dir, cutoff)
        if r is not None and r["total"] > 0:
            results.append(r)

    print("=" * 70)
    print("HEARTBEAT ACTIVITY ANALYSIS (past 12 hours)")
    print("Cutoff:", cutoff.isoformat(), "->", now.isoformat())
    print("=" * 70)

    total_hb = 0
    total_empty = 0
    all_actions: list[tuple[str, dict]] = []

    for r in results:
        total_hb += r["total"]
        total_empty += r["empty"]
        for a in r["all_actions"]:
            all_actions.append((r["name"], a))

        print(f"\n--- {r['name']} ---")
        print(f"  Total heartbeats: {r['total']}")
        print(f"  Empty (no output): {r['empty']}")
        print(f"  Productive: {r['productive']}")

        for i, s in enumerate(r["sessions"]):
            status = "EMPTY" if not s["productive"] else "PRODUCTIVE"
            end_str = s["end_ts"].strftime("%H:%M") if s["end_ts"] else "?"
            print(f"\n  Session {i+1} ({s['start_ts'].strftime('%H:%M')}-{end_str}) [{status}]")
            if s["actions"]:
                for a in s["actions"]:
                    t = a.get("type", "?")
                    extra = ""
                    if t == "message_sent":
                        extra = f" -> {a.get('to', '?')}"
                    elif t == "channel_post":
                        extra = f" -> {a.get('channel', '?')}"
                    elif t == "task_creation":
                        extra = f" ({a.get('tool', '')})"
                    print(f"    - {t}{extra}")

    print("\n" + "=" * 70)
    print("OVERALL SUMMARY")
    print("=" * 70)
    print(f"Total heartbeats: {total_hb}")
    print(f"Empty (wasted): {total_empty}")
    if total_hb > 0:
        pct = 100 * total_empty / total_hb
        print(f"Empty percentage: {pct:.1f}%")
    print(f"Productive: {total_hb - total_empty}")

    print("\n--- All actions taken (to gauge cost justification) ---")
    for anima, a in all_actions:
        t = a.get("type", "?")
        ts = a.get("ts", "")[:19] if a.get("ts") else ""
        to_ch = a.get("to") or a.get("channel") or ""
        print(f"  {anima}: {t} {to_ch} @ {ts}")


if __name__ == "__main__":
    main()
