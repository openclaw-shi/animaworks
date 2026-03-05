#!/usr/bin/env python3
"""
Analyze heartbeat token usage across all AnimaWorks animas for the past 12 hours.
Token usage logs: ~/.animaworks/animas/{name}/token_usage/{date}.jsonl
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

ANIMAWORKS_HOME = Path.home() / ".animaworks"
TOKEN_USAGE_BASE = ANIMAWORKS_HOME / "animas"
JST = timezone(timedelta(hours=9))


def parse_ts(ts_str: str) -> datetime:
    """Parse ISO8601 timestamp to datetime."""
    if ts_str.endswith("+09:00"):
        ts_str = ts_str.replace("+09:00", "+0900")
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def main() -> None:
    now = datetime.now(JST)
    cutoff = now - timedelta(hours=12)
    dates_to_check = [
        (now - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(2)
    ]

    print("=" * 80)
    print("HEARTBEAT TOKEN USAGE ANALYSIS — Past 12 Hours")
    print("=" * 80)
    print(f"Reference time (now):  {now.isoformat()}")
    print(f"Cutoff (12h ago):     {cutoff.isoformat()}")
    print(f"Dates scanned:        {dates_to_check}")
    print()

    heartbeat_entries: list[dict] = []
    all_entries: list[dict] = []

    for anima_dir in sorted(TOKEN_USAGE_BASE.iterdir()):
        if not anima_dir.is_dir():
            continue
        name = anima_dir.name
        if name.startswith("tmp") or name in ("test", "test-anima"):
            continue
        token_dir = anima_dir / "token_usage"
        if not token_dir.exists():
            continue

        for date_str in dates_to_check:
            fpath = token_dir / f"{date_str}.jsonl"
            if not fpath.exists():
                continue
            try:
                with open(fpath) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        obj["_anima"] = name
                        ts_str = obj.get("ts")
                        if not ts_str:
                            continue
                        try:
                            ts = parse_ts(ts_str)
                        except (ValueError, TypeError):
                            continue
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=JST)
                        all_entries.append(obj)
                        trigger = obj.get("trigger") or ""
                        if trigger.startswith("heartbeat"):
                            if ts >= cutoff:
                                heartbeat_entries.append(obj)
            except OSError as e:
                print(f"Warning: could not read {fpath}: {e}")

    if not heartbeat_entries:
        print("No heartbeat entries found in the past 12 hours.")
        return

    by_anima: dict[str, list[dict]] = defaultdict(list)
    for e in heartbeat_entries:
        by_anima[e["_anima"]].append(e)

    by_model: dict[str, list[dict]] = defaultdict(list)
    for e in heartbeat_entries:
        by_model[e.get("model", "unknown")].append(e)

    period_all_entries = [
        e for e in all_entries
        if (e.get("ts") and parse_ts(e["ts"]) >= cutoff)
    ]
    period_all_cost = sum(e.get("estimated_cost_usd") or 0 for e in period_all_entries)
    heartbeat_total_cost = sum(e.get("estimated_cost_usd") or 0 for e in heartbeat_entries)

    durations = [e.get("duration_ms") or 0 for e in heartbeat_entries]
    durations_sorted = sorted(durations)
    n = len(durations_sorted)
    p50 = durations_sorted[n // 2] if n else 0
    p90 = durations_sorted[int(n * 0.9)] if n and n > 1 else (durations_sorted[-1] if durations_sorted else 0)

    print("1. PER-ANIMA HEARTBEAT STATISTICS")
    print("-" * 80)
    print(f"{'Anima':<14} {'Sessions':>8} {'Avg In':>10} {'Avg Out':>10} {'Total Cost':>12} {'Avg Dur(ms)':>12} {'Avg Turns':>10} {'Models':<24}")
    print("-" * 80)

    for name in sorted(by_anima.keys()):
        entries = by_anima[name]
        n_sess = len(entries)
        avg_in = sum(e.get("input_tokens") or 0 for e in entries) / n_sess
        avg_out = sum(e.get("output_tokens") or 0 for e in entries) / n_sess
        cost = sum(e.get("estimated_cost_usd") or 0 for e in entries)
        avg_dur = sum(e.get("duration_ms") or 0 for e in entries) / n_sess
        avg_turns = sum(e.get("turns") or 0 for e in entries) / n_sess
        models = ", ".join(sorted(set(e.get("model", "?") for e in entries)))
        print(f"{name:<14} {n_sess:>8} {avg_in:>10.0f} {avg_out:>10.0f} {cost:>12.4f} {avg_dur:>12.0f} {avg_turns:>10.1f} {models:<24}")

    print()
    print("2. PER-MODEL HEARTBEAT BREAKDOWN")
    print("-" * 80)
    print(f"{'Model':<32} {'Sessions':>10} {'Total Cost':>12} {'Avg In':>10} {'Avg Out':>10}")
    print("-" * 80)
    for model in sorted(by_model.keys()):
        entries = by_model[model]
        n = len(entries)
        cost = sum(e.get("estimated_cost_usd") or 0 for e in entries)
        avg_in = sum(e.get("input_tokens") or 0 for e in entries) / n
        avg_out = sum(e.get("output_tokens") or 0 for e in entries) / n
        print(f"{model:<32} {n:>10} {cost:>12.4f} {avg_in:>10.0f} {avg_out:>10.0f}")
    print()

    print("3. HEARTBEAT DURATION DISTRIBUTION (ms)")
    print("-" * 80)
    print(f"  Min:    {min(durations):>12,}")
    print(f"  Avg:    {sum(durations)/len(durations):>12,.0f}")
    print(f"  Max:    {max(durations):>12,}")
    print(f"  P50:    {p50:>12,}")
    print(f"  P90:    {p90:>12,}")
    print()

    print("4. COST SUMMARY")
    print("-" * 80)
    print(f"  Heartbeat total cost:  ${heartbeat_total_cost:.4f}")
    print(f"  All triggers total:   ${period_all_cost:.4f}")
    if period_all_cost > 0:
        pct = 100 * heartbeat_total_cost / period_all_cost
        print(f"  Heartbeat % of total:   {pct:.1f}%")
    print()

    costs_by_anima = {n: sum(e.get("estimated_cost_usd") or 0 for e in entries) for n, entries in by_anima.items()}
    if costs_by_anima:
        vals = list(costs_by_anima.values())
        median_cost = sorted(vals)[len(vals) // 2] if vals else 0
        threshold = 2 * median_cost
        high_animas = [(n, c) for n, c in costs_by_anima.items() if c > threshold and median_cost > 0]
        print("5. ANIMAS WITH UNUSUALLY HIGH HEARTBEAT COSTS (>2x median)")
        print("-" * 80)
        if high_animas:
            for name, cost in sorted(high_animas, key=lambda x: -x[1]):
                print(f"  {name}: ${cost:.4f} (median: ${median_cost:.4f})")
        else:
            print("  None (all within 2x median).")
    print()

    tokens_by_anima = {n: sum(e.get("total_tokens") or 0 for e in entries) for n, entries in by_anima.items()}
    if tokens_by_anima:
        vals = list(tokens_by_anima.values())
        median_tok = sorted(vals)[len(vals) // 2] if vals else 0
        threshold_tok = 2 * median_tok
        high_tok = [(n, t) for n, t in tokens_by_anima.items() if t > threshold_tok and median_tok > 0]
        print("6. ANIMAS WITH UNUSUALLY HIGH HEARTBEAT TOKEN COUNTS (>2x median)")
        print("-" * 80)
        if high_tok:
            for name, tok in sorted(high_tok, key=lambda x: -x[1]):
                print(f"  {name}: {tok:,} tokens (median: {median_tok:,})")
        else:
            print("  None.")
    print("=" * 80)


if __name__ == "__main__":
    main()
