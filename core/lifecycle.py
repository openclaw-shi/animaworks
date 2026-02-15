from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


import asyncio
import logging
import re
import time
from typing import Any, Callable, Coroutine

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.person import DigitalPerson
from core.schemas import CronTask

logger = logging.getLogger("animaworks.lifecycle")

BroadcastFn = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

# Minimum seconds between consecutive message-triggered heartbeats
# for the same person. Prevents cascading loops (A sends to B, B replies
# to A, A replies to B, …).
_MSG_HEARTBEAT_COOLDOWN_S = 60

_CASCADE_WINDOW_S = 600   # 10 minutes
_CASCADE_THRESHOLD = 4     # max round-trips per pair within window

_DAY_MAP = {
    "月曜": "mon",
    "火曜": "tue",
    "水曜": "wed",
    "木曜": "thu",
    "金曜": "fri",
    "土曜": "sat",
    "日曜": "sun",
}


class LifecycleManager:
    """Manages heartbeat and cron for Digital Persons via APScheduler."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")
        self.persons: dict[str, DigitalPerson] = {}
        self._ws_broadcast: BroadcastFn | None = None
        self._inbox_watcher_task: asyncio.Task | None = None
        self._pending_triggers: set[str] = set()
        self._deferred_inbox: set[str] = set()
        self._last_msg_heartbeat_end: dict[str, float] = {}
        self._pair_heartbeat_times: dict[tuple[str, str], list[float]] = {}

    def set_broadcast(self, fn: BroadcastFn) -> None:
        self._ws_broadcast = fn

    def register_person(self, person: DigitalPerson) -> None:
        self.persons[person.name] = person
        # Wire up lock-release callback for deferred inbox processing
        person.set_on_lock_released(
            lambda n=person.name: asyncio.ensure_future(
                self._on_person_lock_released(n)
            )
        )
        # Wire up schedule-changed callback for hot-reload
        person.set_on_schedule_changed(self.reload_person_schedule)
        self._setup_heartbeat(person)
        self._setup_cron_tasks(person)
        logger.info("Registered '%s' with lifecycle manager", person.name)

    def unregister_person(self, name: str) -> None:
        """Remove a person and all their scheduled jobs."""
        self.persons.pop(name, None)
        self._pending_triggers.discard(name)
        self._deferred_inbox.discard(name)
        # Remove all scheduler jobs belonging to this person
        for job in self.scheduler.get_jobs():
            if job.id.startswith(f"{name}_"):
                job.remove()
        logger.info("Unregistered '%s' from lifecycle manager", name)

    def reload_person_schedule(self, name: str) -> dict[str, Any]:
        """Reload heartbeat and cron schedules for a person from disk.

        Called when heartbeat.md or cron.md is modified at runtime.

        Args:
            name: The person name whose schedule should be reloaded.

        Returns:
            A summary dict with keys ``reloaded``, ``removed``, ``new_jobs``
            (or ``error`` if the person is not registered).
        """
        person = self.persons.get(name)
        if not person:
            logger.warning("reload_person_schedule: '%s' not registered", name)
            return {"error": f"Person '{name}' not registered"}

        # Remove existing heartbeat and cron jobs for this person
        removed = 0
        for job in self.scheduler.get_jobs():
            if job.id.startswith(f"{name}_"):
                job.remove()
                removed += 1

        # Re-setup from current files on disk
        self._setup_heartbeat(person)
        self._setup_cron_tasks(person)

        new_jobs = [
            j.id for j in self.scheduler.get_jobs()
            if j.id.startswith(f"{name}_")
        ]
        logger.info(
            "Reloaded schedule for '%s': removed=%d, new_jobs=%s",
            name, removed, new_jobs,
        )
        return {"reloaded": name, "removed": removed, "new_jobs": new_jobs}

    # ── Heartbeat ─────────────────────────────────────────

    def _setup_heartbeat(self, person: DigitalPerson) -> None:
        config = person.memory.read_heartbeat_config()

        _HEARTBEAT_INTERVAL = 30  # Fixed system-wide; not configurable per person

        active_start, active_end = 9, 22
        m = re.search(r"(\d{1,2}):\d{0,2}\s*-\s*(\d{1,2})", config)
        if m:
            active_start, active_end = int(m.group(1)), int(m.group(2))

        self.scheduler.add_job(
            self._heartbeat_wrapper,
            CronTrigger(
                minute=f"*/{_HEARTBEAT_INTERVAL}",
                hour=f"{active_start}-{active_end - 1}",
            ),
            id=f"{person.name}_heartbeat",
            name=f"{person.name} heartbeat",
            args=[person.name],
            replace_existing=True,
        )
        logger.info(
            "Heartbeat '%s': every %dmin, active %d:00-%d:00",
            person.name,
            _HEARTBEAT_INTERVAL,
            active_start,
            active_end,
        )

    async def _heartbeat_wrapper(self, name: str) -> None:
        person = self.persons.get(name)
        if not person:
            return

        logger.info("Heartbeat: %s", name)
        result = await person.run_heartbeat()
        if self._ws_broadcast:
            await self._ws_broadcast(
                {
                    "type": "person.heartbeat",
                    "data": {"name": name, "result": result.model_dump()},
                }
            )

    # ── Cron ──────────────────────────────────────────────

    def _setup_cron_tasks(self, person: DigitalPerson) -> None:
        config = person.memory.read_cron_config()
        if not config:
            return

        tasks = _parse_cron_md(config)
        for i, task in enumerate(tasks):
            trigger = _parse_schedule(task.schedule)
            if trigger:
                self.scheduler.add_job(
                    self._cron_wrapper,
                    trigger,
                    id=f"{person.name}_cron_{i}",
                    name=f"{person.name}: {task.name}",
                    args=[person.name, task],  # Pass entire CronTask object
                    replace_existing=True,
                )
                logger.info(
                    "Cron '%s': %s (%s) [%s]",
                    person.name,
                    task.name,
                    task.schedule,
                    task.type,
                )

    async def _cron_wrapper(self, name: str, task: CronTask) -> None:
        """Wrapper for cron task execution (both LLM and command types)."""
        person = self.persons.get(name)
        if not person:
            return

        logger.info("Cron: %s -> %s [%s]", name, task.name, task.type)
        # Run cron tasks without awaiting lock — use create_task so
        # multiple simultaneous cron tasks don't block each other.
        asyncio.create_task(
            self._run_cron_and_broadcast(person, name, task),
            name=f"cron-{name}-{task.name}",
        )

    async def _run_cron_and_broadcast(
        self,
        person: DigitalPerson,
        name: str,
        task: CronTask,
    ) -> None:
        """Execute a cron task (LLM or command type) and broadcast the result."""
        try:
            if task.type == "llm":
                # LLM-type: invoke agent.run_cycle
                result = await person.run_cron_task(task.name, task.description)
                broadcast_data = {
                    "type": "person.cron",
                    "data": {
                        "name": name,
                        "task": task.name,
                        "task_type": "llm",
                        "result": result.model_dump(),
                    },
                }
            elif task.type == "command":
                # Command-type: execute bash/tool directly
                result = await person.run_cron_command(
                    task.name,
                    command=task.command,
                    tool=task.tool,
                    args=task.args,
                )
                broadcast_data = {
                    "type": "person.cron",
                    "data": {
                        "name": name,
                        "task": task.name,
                        "task_type": "command",
                        "result": result,
                    },
                }
            else:
                logger.warning(
                    "Unknown cron task type '%s' for %s -> %s",
                    task.type,
                    name,
                    task.name,
                )
                return

            if self._ws_broadcast:
                await self._ws_broadcast(broadcast_data)
        except Exception:
            logger.exception("Cron task failed: %s -> %s", name, task.name)

    # ── Inbox Watcher ──────────────────────────────────────

    def _is_in_cooldown(self, name: str) -> bool:
        """Return True if a message-triggered heartbeat finished too recently."""
        last = self._last_msg_heartbeat_end.get(name, 0.0)
        return (time.monotonic() - last) < _MSG_HEARTBEAT_COOLDOWN_S

    def _check_cascade(self, person_name: str, senders: set[str]) -> bool:
        """Return True if any (person, sender) pair exceeds cascade threshold."""
        now = time.monotonic()
        for sender in senders:
            keys = [(person_name, sender), (sender, person_name)]
            total = 0
            for k in keys:
                times = self._pair_heartbeat_times.get(k, [])
                # Evict expired entries
                times = [t for t in times if now - t < _CASCADE_WINDOW_S]
                self._pair_heartbeat_times[k] = times
                if not times and k in self._pair_heartbeat_times:
                    del self._pair_heartbeat_times[k]
                total += len(times)
            if total >= _CASCADE_THRESHOLD:
                logger.warning(
                    "CASCADE DETECTED: %s <-> %s (%d round-trips in %ds window). "
                    "Suppressing message-triggered heartbeat.",
                    person_name, sender, total, _CASCADE_WINDOW_S,
                )
                return True
        return False

    def _record_pair_heartbeat(self, person_name: str, senders: set[str]) -> None:
        """Record a heartbeat exchange for cascade tracking."""
        now = time.monotonic()
        for sender in senders:
            key = (person_name, sender)
            self._pair_heartbeat_times.setdefault(key, []).append(now)

    async def _inbox_watcher_loop(self) -> None:
        """Poll inbox dirs every 2s; trigger heartbeat on new messages."""
        logger.info("Inbox watcher started (poll interval: 2s)")
        while True:
            await asyncio.sleep(2)
            for name, person in self.persons.items():
                if name in self._pending_triggers:
                    continue
                if not person.messenger.has_unread():
                    continue
                if self._is_in_cooldown(name):
                    continue
                if person._lock.locked():
                    self._deferred_inbox.add(name)
                    continue
                self._pending_triggers.add(name)
                asyncio.create_task(
                    self._message_triggered_heartbeat(name)
                )

    async def _on_person_lock_released(self, name: str) -> None:
        """Check deferred inbox after a person's lock is released."""
        if name not in self._deferred_inbox:
            return
        self._deferred_inbox.discard(name)

        person = self.persons.get(name)
        if not person:
            return
        if not person.messenger.has_unread():
            return
        if name in self._pending_triggers:
            return
        if self._is_in_cooldown(name):
            return

        self._pending_triggers.add(name)
        asyncio.create_task(self._message_triggered_heartbeat(name))

    async def _message_triggered_heartbeat(self, name: str) -> None:
        person = self.persons.get(name)
        if not person:
            self._pending_triggers.discard(name)
            return

        # Peek at inbox senders for cascade detection
        senders = {m.from_person for m in person.messenger.receive()}
        if senders and self._check_cascade(name, senders):
            self._pending_triggers.discard(name)
            return

        try:
            logger.info("Message-triggered heartbeat: %s", name)
            result = await person.run_heartbeat()
            if self._ws_broadcast:
                await self._ws_broadcast(
                    {
                        "type": "person.message_heartbeat",
                        "data": {"name": name, "result": result.model_dump()},
                    }
                )
        except Exception:
            logger.exception("Message-triggered heartbeat failed: %s", name)
        finally:
            self._pending_triggers.discard(name)
            self._last_msg_heartbeat_end[name] = time.monotonic()
            if senders:
                self._record_pair_heartbeat(name, senders)

    # ── System Crons ──────────────────────────────────────

    def _setup_system_crons(self) -> None:
        """Set up system-wide cron tasks for memory consolidation."""
        # Daily consolidation: Every day at 02:00 JST
        self.scheduler.add_job(
            self._handle_daily_consolidation,
            CronTrigger(hour=2, minute=0),
            id="system_daily_consolidation",
            name="System: Daily Consolidation",
            replace_existing=True,
        )
        logger.info("System cron: Daily consolidation at 02:00 JST")

        # Weekly integration: Every Sunday at 03:00 JST
        self.scheduler.add_job(
            self._handle_weekly_integration,
            CronTrigger(day_of_week="sun", hour=3, minute=0),
            id="system_weekly_integration",
            name="System: Weekly Integration",
            replace_existing=True,
        )
        logger.info("System cron: Weekly integration on Sunday at 03:00 JST")

    async def _handle_daily_consolidation(self) -> None:
        """Run daily consolidation for all persons."""
        logger.info("Starting system-wide daily consolidation")

        # Load consolidation config
        from core.config import load_config
        config = load_config()
        consolidation_cfg = getattr(config, "consolidation", None)

        # Default config if not present
        enabled = True
        model = "anthropic/claude-sonnet-4-20250514"
        min_episodes = 1

        if consolidation_cfg:
            enabled = getattr(consolidation_cfg, "daily_enabled", True)
            model = getattr(consolidation_cfg, "llm_model", model)
            min_episodes = getattr(consolidation_cfg, "min_episodes_threshold", 1)

        if not enabled:
            logger.info("Daily consolidation is disabled in config")
            return

        # Run consolidation for each person
        for person_name, person in self.persons.items():
            try:
                from core.memory.consolidation import ConsolidationEngine

                engine = ConsolidationEngine(
                    person_dir=person.memory.person_dir,
                    person_name=person_name,
                )

                result = await engine.daily_consolidate(
                    model=model,
                    min_episodes=min_episodes,
                )

                logger.info(
                    "Daily consolidation for %s: %s",
                    person_name,
                    result
                )

                # Broadcast result via WebSocket
                if self._ws_broadcast and not result.get("skipped"):
                    await self._ws_broadcast(
                        {
                            "type": "system.consolidation",
                            "data": {
                                "person": person_name,
                                "type": "daily",
                                "result": result,
                            },
                        }
                    )

            except Exception:
                logger.exception(
                    "Daily consolidation failed for person=%s",
                    person_name
                )

    async def _handle_weekly_integration(self) -> None:
        """Run weekly integration for all persons."""
        logger.info("Starting system-wide weekly integration")

        # Load config
        from core.config import load_config
        config = load_config()
        consolidation_cfg = getattr(config, "consolidation", None)

        # Default config
        enabled = True  # Phase 3 implementation
        model = "anthropic/claude-sonnet-4-20250514"
        duplicate_threshold = 0.85
        episode_retention_days = 30

        if consolidation_cfg:
            enabled = getattr(consolidation_cfg, "weekly_enabled", True)
            model = getattr(consolidation_cfg, "llm_model", model)
            duplicate_threshold = getattr(consolidation_cfg, "duplicate_threshold", 0.85)
            episode_retention_days = getattr(consolidation_cfg, "episode_retention_days", 30)

        if not enabled:
            logger.info("Weekly integration is disabled in config")
            return

        # Run integration for each person
        for person_name, person in self.persons.items():
            try:
                from core.memory.consolidation import ConsolidationEngine

                engine = ConsolidationEngine(
                    person_dir=person.memory.person_dir,
                    person_name=person_name,
                )

                result = await engine.weekly_integrate(
                    model=model,
                    duplicate_threshold=duplicate_threshold,
                    episode_retention_days=episode_retention_days,
                )

                logger.info(
                    "Weekly integration for %s: merged=%d compressed=%d",
                    person_name,
                    len(result.get("knowledge_files_merged", [])),
                    result.get("episodes_compressed", 0)
                )

                # Broadcast result
                if self._ws_broadcast and not result.get("skipped"):
                    await self._ws_broadcast(
                        {
                            "type": "system.consolidation",
                            "data": {
                                "person": person_name,
                                "type": "weekly",
                                "result": result,
                            },
                        }
                    )

            except Exception:
                logger.exception(
                    "Weekly integration failed for person=%s",
                    person_name
                )

    # ── Lifecycle ─────────────────────────────────────────

    def start(self) -> None:
        self.scheduler.start()
        self._setup_system_crons()
        self._inbox_watcher_task = asyncio.create_task(
            self._inbox_watcher_loop()
        )
        logger.info("Lifecycle manager started (scheduler + inbox watcher + system crons)")

    def shutdown(self) -> None:
        if self._inbox_watcher_task:
            self._inbox_watcher_task.cancel()
        self.scheduler.shutdown(wait=False)
        logger.info("Lifecycle manager stopped")


# ── Parsing helpers ───────────────────────────────────────


def _parse_cron_md(content: str) -> list[CronTask]:
    """Parse cron.md to extract CronTask definitions.

    Supports both LLM-type and command-type tasks:

    LLM-type:
        ## Task Name (schedule)
        type: llm
        Description text...

    Command-type (bash):
        ## Task Name (schedule)
        type: command
        command: /path/to/script.sh

    Command-type (tool):
        ## Task Name (schedule)
        type: command
        tool: tool_name
        args:
          key: value
    """
    tasks: list[CronTask] = []
    cur_name = ""
    cur_sched = ""
    cur_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith("## "):
            if cur_name:
                tasks.append(_parse_single_cron_task(cur_name, cur_sched, cur_lines))
            header = line[3:].strip()
            sm = re.search(r"[（(](.+?)[）)]", header)
            if sm:
                cur_sched = sm.group(1)
                cur_name = header[: header.find("（" if "（" in header else "(")].strip()
            else:
                cur_name = header
                cur_sched = ""
            cur_lines = []
        elif cur_name:
            cur_lines.append(line)

    if cur_name:
        tasks.append(_parse_single_cron_task(cur_name, cur_sched, cur_lines))
    return tasks


def _parse_single_cron_task(name: str, schedule: str, lines: list[str]) -> CronTask:
    """Parse a single cron task definition from body lines."""
    task_type = "llm"
    command = None
    tool = None
    args = None
    description_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("type:"):
            task_type = stripped[5:].strip()
        elif stripped.startswith("command:"):
            command = stripped[8:].strip()
        elif stripped.startswith("tool:"):
            tool = stripped[5:].strip()
        elif stripped.startswith("args:"):
            # Parse YAML args block (indented lines following "args:")
            yaml_lines = [line]
            i += 1
            while i < len(lines):
                next_line = lines[i]
                # Continue if line is indented or empty
                if next_line.startswith("  ") or not next_line.strip():
                    yaml_lines.append(next_line)
                    i += 1
                else:
                    break
            i -= 1  # Back one line for outer loop increment

            # Parse YAML
            try:
                parsed = yaml.safe_load("\n".join(yaml_lines))
                if parsed and "args" in parsed:
                    args = parsed["args"]
            except yaml.YAMLError as e:
                logger.warning("Failed to parse args YAML for task %s: %s", name, e)
        else:
            # Regular description line
            description_lines.append(line)

        i += 1

    return CronTask(
        name=name,
        schedule=schedule,
        type=task_type,
        description="\n".join(description_lines).strip(),
        command=command,
        tool=tool,
        args=args,
    )


_NTH_DAY_RANGE = {
    1: "1-7",
    2: "8-14",
    3: "15-21",
    4: "22-28",
}


def _parse_schedule(schedule: str) -> CronTrigger | None:
    s = schedule.strip()
    # Remove trailing timezone markers (JST, UTC, etc.)
    s = re.sub(r"\s+[A-Z]{2,4}$", "", s)

    # 毎日 9:00
    m = re.match(r"毎日\s+(\d{1,2}):(\d{2})", s)
    if m:
        return CronTrigger(hour=int(m.group(1)), minute=int(m.group(2)))

    # 平日 9:00
    m = re.match(r"平日\s+(\d{1,2}):(\d{2})", s)
    if m:
        return CronTrigger(
            day_of_week="mon-fri", hour=int(m.group(1)), minute=int(m.group(2))
        )

    # 毎週金曜 17:00
    m = re.match(r"毎週(.+?)\s+(\d{1,2}):(\d{2})", s)
    if m:
        day = _DAY_MAP.get(m.group(1), "fri")
        return CronTrigger(
            day_of_week=day, hour=int(m.group(2)), minute=int(m.group(3))
        )

    # 隔週金曜 17:00
    m = re.match(r"隔週(.+?)\s+(\d{1,2}):(\d{2})", s)
    if m:
        day = _DAY_MAP.get(m.group(1), "fri")
        return CronTrigger(
            day_of_week=day, week="*/2", hour=int(m.group(2)), minute=int(m.group(3))
        )

    # 第2火曜 10:00 (Nth weekday of month)
    m = re.match(r"第(\d)(.+?)\s+(\d{1,2}):(\d{2})", s)
    if m:
        nth = int(m.group(1))
        day = _DAY_MAP.get(m.group(2), "mon")
        day_range = _NTH_DAY_RANGE.get(nth)
        if day_range:
            return CronTrigger(
                day=day_range,
                day_of_week=day,
                hour=int(m.group(3)),
                minute=int(m.group(4)),
            )

    # 毎月1日 9:00
    m = re.match(r"毎月(\d{1,2})日\s+(\d{1,2}):(\d{2})", s)
    if m:
        return CronTrigger(
            day=int(m.group(1)), hour=int(m.group(2)), minute=int(m.group(3))
        )

    # 毎月最終日 18:00
    m = re.match(r"毎月最終日\s+(\d{1,2}):(\d{2})", s)
    if m:
        return CronTrigger(
            day="last", hour=int(m.group(1)), minute=int(m.group(2))
        )

    # Standard cron: */5 * * * *
    if re.match(r"^[\d\*\/\-\,]+(\s+[\d\*\/\-\,]+){4}$", s):
        parts = s.split()
        return CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

    logger.warning("Could not parse schedule: '%s'", s)
    return None