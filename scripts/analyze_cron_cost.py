#!/usr/bin/env python3
"""
Analyze CRON token usage and cost structure in AnimaWorks (past 24h).

Determines whether cron should get a model override mechanism by:
1. Comparing cron vs heartbeat cost and token usage
2. Categorizing cron jobs by type (llm vs command-triggered-llm) and complexity
3. Documenting the execution path and model resolution

Token usage logs: ~/.animaworks/animas/{name}/token_usage/{date}.jsonl
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

ANIMAWORKS_HOME = Path.home() / ".animaworks"
TOKEN_USAGE_BASE = ANIMAWORKS_HOME / "animas"
CRON_MD_BASE = ANIMAWORKS_HOME / "animas"
JST = timezone(timedelta(hours=9))


def parse_ts(ts_str: str) -> datetime:
    """Parse ISO8601 timestamp to datetime."""
    if not ts_str:
        raise ValueError("empty ts")
    if ts_str.endswith("+09:00"):
        ts_str = ts_str.replace("+09:00", "+0900")
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def _effective_input(e: dict) -> int:
    """Effective input tokens (input + cache_read for S mode)."""
    inp = e.get("input_tokens") or 0
    cache = e.get("cache_read_tokens") or 0
    return inp + cache if (inp == 0 and cache > 0) else inp


def main() -> None:
    now = datetime.now(JST)
    cutoff = now - timedelta(hours=24)
    dates_to_check = [
        (now - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(2)
    ]

    print("=" * 80)
    print("CRON COST ANALYSIS — Past 24 Hours")
    print("=" * 80)
    print(f"Reference time (now):  {now.isoformat()}")
    print(f"Cutoff (24h ago):     {cutoff.isoformat()}")
    print(f"Dates scanned:        {dates_to_check}")
    print()

    cron_entries: list[dict] = []
    heartbeat_entries: list[dict] = []
    all_entries: list[dict] = []

    for anima_dir in sorted(TOKEN_USAGE_BASE.iterdir()):
        if not anima_dir.is_dir():
            continue
        name = anima_dir.name
        if name.startswith("tmp") or name in ("test", "test-anima", "anima_"):
            continue
        token_dir = anima_dir / "token_usage"
        if not token_dir.exists():
            continue

        for date_str in dates_to_check:
            fpath = token_dir / f"{date_str}.jsonl"
            if not fpath.exists():
                continue
            try:
                with open(fpath, errors="ignore") as f:
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
                        if trigger.startswith("cron:"):
                            if ts >= cutoff:
                                cron_entries.append(obj)
                        elif trigger == "heartbeat":
                            if ts >= cutoff:
                                heartbeat_entries.append(obj)
            except OSError as e:
                print(f"Warning: could not read {fpath}: {e}")

    # 1. CRON COST BREAKDOWN BY JOB TYPE
    print("1. CRON COST BREAKDOWN BY JOB TYPE (past 24h)")
    print("-" * 80)
    by_job: dict[str, list[dict]] = defaultdict(list)
    for e in cron_entries:
        job = (e.get("trigger") or "").replace("cron:", "")
        by_job[job].append(e)

    by_job_sorted = sorted(
        by_job.items(),
        key=lambda x: -sum(e.get("estimated_cost_usd") or 0 for e in x[1]),
    )

    print(f"{'Job Name':<55} {'Sessions':>8} {'Total $':>10} {'Avg In':>10} {'Avg Out':>10} {'Models':<24}")
    print("-" * 80)
    for job_name, entries in by_job_sorted[:25]:
        n = len(entries)
        cost = sum(e.get("estimated_cost_usd") or 0 for e in entries)
        avg_in = sum(_effective_input(e) for e in entries) / n if n else 0
        avg_out = sum(e.get("output_tokens") or 0 for e in entries) / n if n else 0
        models = ", ".join(sorted(set(e.get("model", "?") for e in entries)))
        print(f"{job_name[:54]:<55} {n:>8} {cost:>10.4f} {avg_in:>10.0f} {avg_out:>10.0f} {models[:23]:<24}")

    print()

    # 2. CRON vs HEARTBEAT COMPARISON
    print("2. CRON vs HEARTBEAT COMPARISON (past 24h)")
    print("-" * 80)
    cron_total_cost = sum(e.get("estimated_cost_usd") or 0 for e in cron_entries)
    hb_total_cost = sum(e.get("estimated_cost_usd") or 0 for e in heartbeat_entries)
    period_all = [e for e in all_entries if e.get("ts") and parse_ts(e["ts"]) >= cutoff]
    period_cost = sum(e.get("estimated_cost_usd") or 0 for e in period_all)

    print(f"  Cron sessions:      {len(cron_entries):>8}")
    print(f"  Cron total cost:     ${cron_total_cost:>10.4f}")
    print(f"  Heartbeat sessions:  {len(heartbeat_entries):>8}")
    print(f"  Heartbeat cost:      ${hb_total_cost:>10.4f}")
    print(f"  All triggers cost:  ${period_cost:>10.4f}")
    if period_cost > 0:
        print(f"  Cron % of total:      {100 * cron_total_cost / period_cost:>6.1f}%")
        print(f"  Heartbeat % of total:{100 * hb_total_cost / period_cost:>6.1f}%")
    print()

    # 3. CRON BY MODEL
    print("3. CRON BY MODEL")
    print("-" * 80)
    by_model: dict[str, list[dict]] = defaultdict(list)
    for e in cron_entries:
        by_model[e.get("model", "unknown")].append(e)

    print(f"{'Model':<36} {'Sessions':>10} {'Total Cost':>12} {'Avg In':>10} {'Avg Out':>10}")
    print("-" * 80)
    for model in sorted(by_model.keys()):
        entries = by_model[model]
        n = len(entries)
        cost = sum(e.get("estimated_cost_usd") or 0 for e in entries)
        avg_in = sum(_effective_input(e) for e in entries) / n if n else 0
        avg_out = sum(e.get("output_tokens") or 0 for e in entries) / n if n else 0
        print(f"{model:<36} {n:>10} {cost:>12.4f} {avg_in:>10.0f} {avg_out:>10.0f}")
    print()

    # 4. CRON BY ANIMA
    print("4. CRON BY ANIMA")
    print("-" * 80)
    by_anima: dict[str, list[dict]] = defaultdict(list)
    for e in cron_entries:
        by_anima[e["_anima"]].append(e)

    print(f"{'Anima':<14} {'Sessions':>8} {'Total Cost':>12} {'Avg In':>10} {'Avg Out':>10}")
    print("-" * 80)
    for name in sorted(by_anima.keys()):
        entries = by_anima[name]
        n = len(entries)
        cost = sum(e.get("estimated_cost_usd") or 0 for e in entries)
        avg_in = sum(_effective_input(e) for e in entries) / n if n else 0
        avg_out = sum(e.get("output_tokens") or 0 for e in entries) / n if n else 0
        print(f"{name:<14} {n:>8} {cost:>12.4f} {avg_in:>10.0f} {avg_out:>10.0f}")
    print()

    # 5. CRON.MD EXAMPLES
    print("5. CRON.MD EXAMPLES (job complexity: llm vs command)")
    print("-" * 80)
    sample_animas = ["sakura", "rin", "kotoha", "mei", "shizuku", "yuki", "tsumugi"]
    for anima in sample_animas:
        cron_md = CRON_MD_BASE / anima / "cron.md"
        if cron_md.exists():
            content = cron_md.read_text(errors="ignore")
            llm_count = content.count("type: llm")
            cmd_count = content.count("type: command")
            print(f"  {anima}: llm={llm_count}, command={cmd_count}")

    print()
    print("  Examples: mei=毎朝の業務計画(llm), Gmailチェック(cmd); shizuku=/tmp cleanup(cmd, skip_pattern)")

    # 6. RECOMMENDATION
    print("6. MODEL OVERRIDE RECOMMENDATION")
    print("-" * 80)
    print("""
EXECUTION PATH (core/_anima_lifecycle.py, agent.py):
  - Cron and heartbeat both call agent.run_cycle(prompt, trigger="cron:"|"heartbeat")
  - Model resolved from status.json (model_config) — same for ALL triggers
  - No background_model or cron_model override exists today

CRON JOB COMPLEXITY:
  - type: llm  → Full LLM session (judgment, planning, report). May need high intelligence.
  - type: command → Bash/tool runs; output analyzed by LLM when skip_pattern matches.
    Many command-type crons are simple pattern checks and could use cheaper models.

RECOMMENDATION:
  - YES: Cron benefits from model override. Many cron jobs are simple and do not need Claude Opus.
  - YES: A single background_model in status.json could cover BOTH heartbeat AND cron.
    Both use the same execution path (run_cycle with _background_lock).
  - Implementation: Add optional "background_model" to status.json. When set, use it
    for trigger in ("heartbeat",) or trigger.startswith("cron:"). Fallback to model.
""")
    print("=" * 80)


if __name__ == "__main__":
    main()
