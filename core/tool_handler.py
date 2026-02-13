from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


"""Tool call dispatcher and permission enforcement.

``ToolHandler`` is the single entry-point for all synchronous tool execution.
It owns permission checks, memory/file/command operations, and delegates
external tool calls to ``ExternalToolDispatcher``.
"""

import asyncio
import logging
import re
import shlex
import subprocess
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from core.external_tools import ExternalToolDispatcher
from core.memory import MemoryManager
from core.messenger import Messenger

logger = logging.getLogger("animaworks.tool_handler")

# Type alias for the delegate callback injected by server/app.py.
DelegateFn = Callable[[str, str, str | None], Coroutine[Any, Any, str]]

# Type alias for the message-sent callback (from, to, content).
OnMessageSentFn = Callable[[str, str, str], None]

# Default delegation timeout in seconds.
_DELEGATE_TIMEOUT_S: int = 300

# Shell metacharacters that indicate injection attempts.
_SHELL_METACHAR_RE = re.compile(r"[;&|`$(){}]")


class ToolHandler:
    """Dispatches tool calls to the appropriate handler.

    Handles memory tools, file operations, command execution,
    delegation, and external tool dispatch.
    """

    def __init__(
        self,
        person_dir: Path,
        memory: MemoryManager,
        messenger: Messenger | None = None,
        tool_registry: list[str] | None = None,
        personal_tools: dict[str, str] | None = None,
        delegate_fn: DelegateFn | None = None,
        on_message_sent: OnMessageSentFn | None = None,
    ) -> None:
        self._person_dir = person_dir
        self._memory = memory
        self._messenger = messenger
        self._delegate_fn = delegate_fn
        self._on_message_sent = on_message_sent
        self._external = ExternalToolDispatcher(
            tool_registry or [],
            personal_tools=personal_tools,
        )

    # ── Delegate callback property ───────────────────────────

    @property
    def delegate_fn(self) -> DelegateFn | None:
        return self._delegate_fn

    @delegate_fn.setter
    def delegate_fn(self, fn: DelegateFn | None) -> None:
        self._delegate_fn = fn

    @property
    def on_message_sent(self) -> OnMessageSentFn | None:
        return self._on_message_sent

    @on_message_sent.setter
    def on_message_sent(self, fn: OnMessageSentFn | None) -> None:
        self._on_message_sent = fn

    # ── Main dispatch ────────────────────────────────────────

    def handle(self, name: str, args: dict[str, Any]) -> str:
        """Synchronous tool call dispatch.

        Routes by tool name to the appropriate handler method.
        Returns the tool result as a string.
        """
        logger.debug("tool_call name=%s args_keys=%s", name, list(args.keys()))

        # Memory tools
        if name == "search_memory":
            return self._handle_search_memory(args)
        if name == "read_memory_file":
            return self._handle_read_memory_file(args)
        if name == "write_memory_file":
            return self._handle_write_memory_file(args)
        if name == "send_message":
            return self._handle_send_message(args)

        # File operation tools
        if name == "read_file":
            return self._handle_read_file(args)
        if name == "write_file":
            return self._handle_write_file(args)
        if name == "edit_file":
            return self._handle_edit_file(args)
        if name == "execute_command":
            return self._handle_execute_command(args)

        # External tool dispatch — inject person_dir for tools that need it
        ext_args = {**args, "person_dir": str(self._person_dir)}
        result = self._external.dispatch(name, ext_args)
        if result is not None:
            return result

        logger.warning("Unknown tool requested: %s", name)
        return f"Unknown tool: {name}"

    async def handle_delegate(self, args: dict[str, Any]) -> str:
        """Handle the ``delegate_task`` tool call (async).

        Enforces a timeout to prevent indefinite blocking when the
        subordinate hangs or takes excessively long.
        """
        if not self._delegate_fn:
            return "Error: delegation not configured for this person"
        target = args.get("to", "")
        task = args.get("task", "")
        context = args.get("context")
        if not target or not task:
            return "Error: 'to' and 'task' are required"
        logger.info("delegate_task to=%s task=%s", target, task[:100])
        try:
            result = await asyncio.wait_for(
                self._delegate_fn(target, task, context),
                timeout=_DELEGATE_TIMEOUT_S,
            )
            logger.info("delegate_task completed, result_len=%d", len(result))
            return result
        except asyncio.TimeoutError:
            logger.error(
                "delegate_task timed out after %ds: to=%s",
                _DELEGATE_TIMEOUT_S,
                target,
            )
            return (
                f"Delegation to '{target}' timed out after "
                f"{_DELEGATE_TIMEOUT_S}s. The subordinate may still be "
                f"running — consider checking their status or retrying."
            )
        except Exception as e:
            logger.error("delegate_task failed: %s", e)
            return f"Delegation failed: {e}"

    # ── Memory tool handlers ─────────────────────────────────

    def _handle_search_memory(self, args: dict[str, Any]) -> str:
        scope = args.get("scope", "all")
        query = args.get("query", "")
        results = self._memory.search_memory_text(query, scope=scope)
        logger.debug(
            "search_memory query=%s scope=%s results=%d",
            query, scope, len(results),
        )
        if not results:
            return f"No results for '{query}'"
        return "\n".join(f"- {fname}: {line}" for fname, line in results[:10])

    def _handle_read_memory_file(self, args: dict[str, Any]) -> str:
        path = self._person_dir / args["path"]
        if path.exists() and path.is_file():
            logger.debug("read_memory_file path=%s", args["path"])
            return path.read_text(encoding="utf-8")
        logger.debug("read_memory_file NOT FOUND path=%s", args["path"])
        return f"File not found: {args['path']}"

    def _handle_write_memory_file(self, args: dict[str, Any]) -> str:
        path = self._person_dir / args["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if args.get("mode") == "append":
            with open(path, "a", encoding="utf-8") as f:
                f.write(args["content"])
        else:
            path.write_text(args["content"], encoding="utf-8")
        logger.info(
            "write_memory_file path=%s mode=%s",
            args["path"], args.get("mode", "overwrite"),
        )
        return f"Written to {args['path']}"

    def _handle_send_message(self, args: dict[str, Any]) -> str:
        if not self._messenger:
            return "Error: messenger not configured"
        msg = self._messenger.send(
            to=args["to"],
            content=args["content"],
            thread_id=args.get("thread_id", ""),
            reply_to=args.get("reply_to", ""),
        )
        logger.info("send_message to=%s thread=%s", args["to"], msg.thread_id)

        if self._on_message_sent:
            try:
                self._on_message_sent(
                    self._messenger.person_name, args["to"], args["content"],
                )
            except Exception:
                logger.exception("on_message_sent callback failed")

        return f"Message sent to {args['to']} (id: {msg.id}, thread: {msg.thread_id})"

    # ── File operation handlers ──────────────────────────────

    def _handle_read_file(self, args: dict[str, Any]) -> str:
        path_str = args.get("path", "")
        err = self._check_file_permission(path_str)
        if err:
            return err
        path = Path(path_str)
        if not path.exists():
            return f"File not found: {path_str}"
        if not path.is_file():
            return f"Not a file: {path_str}"
        try:
            content = path.read_text(encoding="utf-8")
            logger.info("read_file path=%s len=%d", path_str, len(content))
            return content[:100_000]  # cap at 100k chars
        except Exception as e:
            return f"Error reading {path_str}: {e}"

    def _handle_write_file(self, args: dict[str, Any]) -> str:
        path_str = args.get("path", "")
        err = self._check_file_permission(path_str)
        if err:
            return err
        path = Path(path_str)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args.get("content", ""), encoding="utf-8")
            logger.info("write_file path=%s", path_str)
            return f"Written to {path_str}"
        except Exception as e:
            return f"Error writing {path_str}: {e}"

    def _handle_edit_file(self, args: dict[str, Any]) -> str:
        path_str = args.get("path", "")
        err = self._check_file_permission(path_str)
        if err:
            return err
        path = Path(path_str)
        if not path.exists():
            return f"File not found: {path_str}"
        try:
            content = path.read_text(encoding="utf-8")
            old = args.get("old_string", "")
            new = args.get("new_string", "")
            if old not in content:
                return f"old_string not found in {path_str}"
            count = content.count(old)
            if count > 1:
                return (
                    f"old_string matches {count} locations "
                    "— provide more context to make it unique"
                )
            content = content.replace(old, new, 1)
            path.write_text(content, encoding="utf-8")
            logger.info("edit_file path=%s", path_str)
            return f"Edited {path_str}"
        except Exception as e:
            return f"Error editing {path_str}: {e}"

    def _handle_execute_command(self, args: dict[str, Any]) -> str:
        command = args.get("command", "")
        err = self._check_command_permission(command)
        if err:
            return err
        timeout = args.get("timeout", 30)
        try:
            argv = shlex.split(command)
        except ValueError as e:
            return f"Error parsing command: {e}"
        try:
            proc = subprocess.run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self._person_dir),
            )
            output = proc.stdout
            if proc.stderr:
                output += f"\n[stderr]\n{proc.stderr}"
            logger.info(
                "execute_command cmd=%s rc=%d", command[:80], proc.returncode,
            )
            return output[:50_000] or f"(exit code {proc.returncode})"
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s"
        except Exception as e:
            return f"Error executing command: {e}"

    # ── Permission checks ────────────────────────────────────

    def _check_file_permission(self, path: str) -> str | None:
        """Check if the file path is allowed by permissions.md.

        Returns ``None`` if allowed, or an error message string if denied.

        Access rules (evaluated in order):
          1. Own person_dir — always allowed
          2. Paths listed under ``ファイル操作`` section in permissions.md
          3. Everything else — denied
        """
        resolved = Path(path).resolve()

        # Always allow access to own person_dir
        if resolved.is_relative_to(self._person_dir.resolve()):
            return None

        permissions = self._memory.read_permissions()
        if "ファイル操作" not in permissions:
            return "Permission denied: file operations not enabled in permissions.md"

        # Parse allowed directory whitelist from permissions.md
        allowed_dirs: list[Path] = []
        in_file_section = False
        for line in permissions.splitlines():
            stripped = line.strip()
            if "ファイル操作" in stripped:
                in_file_section = True
                continue
            if in_file_section and stripped.startswith("#"):
                break
            if in_file_section and stripped.startswith("-"):
                dir_path = stripped.lstrip("- ").split(":")[0].strip()
                if dir_path.startswith("/"):
                    allowed_dirs.append(Path(dir_path).resolve())

        if not allowed_dirs:
            return (
                "Permission denied: no allowed paths listed under ファイル操作. "
                "Add directory paths (e.g. '- /path/to/dir/') to permissions.md."
            )

        for allowed in allowed_dirs:
            if resolved.is_relative_to(allowed):
                return None

        return (
            f"Permission denied: '{path}' is not under any allowed directory. "
            f"Allowed: {[str(d) for d in allowed_dirs]}"
        )

    def _check_command_permission(self, command: str) -> str | None:
        """Check if the command is in the allowed list from permissions.md.

        Returns ``None`` if allowed, or an error message string if denied.
        Rejects commands containing shell metacharacters to prevent injection.
        """
        if not command or not command.strip():
            return "Permission denied: empty command"

        # Reject shell metacharacters regardless of permissions
        if _SHELL_METACHAR_RE.search(command):
            return (
                "Permission denied: command contains shell metacharacters "
                f"({_SHELL_METACHAR_RE.pattern}). "
                "Use separate tool calls instead of chaining commands."
            )

        permissions = self._memory.read_permissions()
        if "コマンド実行" not in permissions:
            return "Permission denied: command execution not enabled in permissions.md"

        # Parse the command safely
        try:
            argv = shlex.split(command)
        except ValueError as e:
            return f"Permission denied: invalid command syntax: {e}"

        if not argv:
            return "Permission denied: empty command after parsing"

        # Extract allowed commands (lines like "- git: OK" or "- npm: OK")
        allowed: list[str] = []
        in_cmd_section = False
        for line in permissions.splitlines():
            stripped = line.strip()
            if "コマンド実行" in stripped:
                in_cmd_section = True
                continue
            if in_cmd_section and stripped.startswith("#"):
                break
            if in_cmd_section and stripped.startswith("-"):
                cmd_name = stripped.lstrip("- ").split(":")[0].strip()
                if cmd_name:
                    allowed.append(cmd_name)
        if not allowed:
            return None  # No explicit list = allow all (section exists)

        cmd_base = argv[0]
        if cmd_base not in allowed:
            return f"Permission denied: command '{cmd_base}' not in allowed list {allowed}"
        return None