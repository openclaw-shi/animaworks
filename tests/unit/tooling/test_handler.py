"""Tests for core.tooling.handler — ToolHandler permission and dispatch."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.tooling.handler import ToolHandler, _SHELL_METACHAR_RE


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def person_dir(tmp_path: Path) -> Path:
    d = tmp_path / "persons" / "test-person"
    d.mkdir(parents=True)
    (d / "permissions.md").write_text("", encoding="utf-8")
    return d


@pytest.fixture
def memory(person_dir: Path) -> MagicMock:
    m = MagicMock()
    m.read_permissions.return_value = ""
    m.search_memory_text.return_value = []
    return m


@pytest.fixture
def messenger() -> MagicMock:
    m = MagicMock()
    m.person_name = "test-person"
    msg = MagicMock()
    msg.id = "msg_001"
    msg.thread_id = "thread_001"
    m.send.return_value = msg
    return m


@pytest.fixture
def handler(person_dir: Path, memory: MagicMock) -> ToolHandler:
    return ToolHandler(
        person_dir=person_dir,
        memory=memory,
        messenger=None,
        tool_registry=[],
    )


@pytest.fixture
def handler_with_messenger(
    person_dir: Path, memory: MagicMock, messenger: MagicMock,
) -> ToolHandler:
    return ToolHandler(
        person_dir=person_dir,
        memory=memory,
        messenger=messenger,
        tool_registry=[],
    )


# ── Properties ────────────────────────────────────────────────


class TestProperties:
    def test_on_message_sent_property(self, handler: ToolHandler):
        assert handler.on_message_sent is None
        fn = MagicMock()
        handler.on_message_sent = fn
        assert handler.on_message_sent is fn

    def test_replied_to(self, handler: ToolHandler):
        assert handler.replied_to == set()

    def test_reset_replied_to(self, handler_with_messenger: ToolHandler):
        h = handler_with_messenger
        h.handle("send_message", {"to": "alice", "content": "hi"})
        assert "alice" in h.replied_to
        h.reset_replied_to()
        assert h.replied_to == set()


# ── Main dispatch routing ─────────────────────────────────────


class TestHandleRouting:
    def test_search_memory(self, handler: ToolHandler, memory: MagicMock):
        memory.search_memory_text.return_value = [
            ("knowledge/k1.md", "some result"),
        ]
        result = handler.handle("search_memory", {"query": "test", "scope": "all"})
        assert "knowledge/k1.md" in result
        assert "some result" in result

    def test_search_memory_no_results(self, handler: ToolHandler, memory: MagicMock):
        memory.search_memory_text.return_value = []
        result = handler.handle("search_memory", {"query": "nothing"})
        assert "No results" in result

    def test_read_memory_file(self, handler: ToolHandler, person_dir: Path):
        (person_dir / "knowledge").mkdir(exist_ok=True)
        (person_dir / "knowledge" / "test.md").write_text("content here", encoding="utf-8")
        result = handler.handle("read_memory_file", {"path": "knowledge/test.md"})
        assert result == "content here"

    def test_read_memory_file_not_found(self, handler: ToolHandler):
        result = handler.handle("read_memory_file", {"path": "nonexistent.md"})
        assert "File not found" in result

    def test_write_memory_file_overwrite(self, handler: ToolHandler, person_dir: Path):
        result = handler.handle(
            "write_memory_file",
            {"path": "knowledge/new.md", "content": "new content"},
        )
        assert "Written to" in result
        assert (person_dir / "knowledge" / "new.md").read_text(encoding="utf-8") == "new content"

    def test_write_memory_file_append(self, handler: ToolHandler, person_dir: Path):
        (person_dir / "knowledge").mkdir(exist_ok=True)
        (person_dir / "knowledge" / "log.md").write_text("line1\n", encoding="utf-8")
        handler.handle(
            "write_memory_file",
            {"path": "knowledge/log.md", "content": "line2\n", "mode": "append"},
        )
        content = (person_dir / "knowledge" / "log.md").read_text(encoding="utf-8")
        assert content == "line1\nline2\n"

    def test_send_message_without_messenger(self, handler: ToolHandler):
        result = handler.handle("send_message", {"to": "alice", "content": "hi"})
        assert "Error" in result

    def test_send_message_with_messenger(self, handler_with_messenger: ToolHandler):
        result = handler_with_messenger.handle(
            "send_message", {"to": "alice", "content": "hello"},
        )
        assert "Message sent to alice" in result
        assert "alice" in handler_with_messenger.replied_to

    def test_send_message_calls_on_message_sent(
        self, handler_with_messenger: ToolHandler,
    ):
        callback = MagicMock()
        handler_with_messenger.on_message_sent = callback
        handler_with_messenger.handle(
            "send_message", {"to": "alice", "content": "hello"},
        )
        callback.assert_called_once_with("test-person", "alice", "hello")

    def test_send_message_on_message_sent_error_swallowed(
        self, handler_with_messenger: ToolHandler,
    ):
        callback = MagicMock(side_effect=RuntimeError("boom"))
        handler_with_messenger.on_message_sent = callback
        # Should not raise
        result = handler_with_messenger.handle(
            "send_message", {"to": "alice", "content": "hello"},
        )
        assert "Message sent" in result

    def test_unknown_tool(self, handler: ToolHandler):
        result = handler.handle("totally_unknown_tool", {})
        assert "Unknown tool" in result

    def test_external_dispatch(self, handler: ToolHandler):
        handler._external = MagicMock()
        handler._external.dispatch.return_value = "external result"
        result = handler.handle("some_external_tool", {"arg": "val"})
        assert result == "external result"

    def test_external_dispatch_returns_none_falls_to_unknown(self, handler: ToolHandler):
        handler._external = MagicMock()
        handler._external.dispatch.return_value = None
        result = handler.handle("some_external_tool", {"arg": "val"})
        assert "Unknown tool" in result


# ── File operation handlers ───────────────────────────────────


class TestFileOperations:
    def test_read_file_in_person_dir(self, handler: ToolHandler, person_dir: Path):
        (person_dir / "test.txt").write_text("hello", encoding="utf-8")
        result = handler.handle("read_file", {"path": str(person_dir / "test.txt")})
        assert result == "hello"

    def test_read_file_not_found(self, handler: ToolHandler, person_dir: Path):
        result = handler.handle("read_file", {"path": str(person_dir / "missing.txt")})
        assert "File not found" in result

    def test_read_file_not_a_file(self, handler: ToolHandler, person_dir: Path):
        result = handler.handle("read_file", {"path": str(person_dir)})
        assert "Not a file" in result

    def test_read_file_truncated_at_100k(self, handler: ToolHandler, person_dir: Path):
        big_content = "x" * 200_000
        (person_dir / "big.txt").write_text(big_content, encoding="utf-8")
        result = handler.handle("read_file", {"path": str(person_dir / "big.txt")})
        assert len(result) == 100_000

    def test_read_file_permission_denied(self, handler: ToolHandler):
        result = handler.handle("read_file", {"path": "/etc/passwd"})
        assert "Permission denied" in result

    def test_write_file_in_person_dir(self, handler: ToolHandler, person_dir: Path):
        path = person_dir / "output.txt"
        result = handler.handle("write_file", {"path": str(path), "content": "data"})
        assert "Written to" in result
        assert path.read_text(encoding="utf-8") == "data"

    def test_write_file_permission_denied(self, handler: ToolHandler):
        result = handler.handle("write_file", {"path": "/etc/no", "content": "data"})
        assert "Permission denied" in result

    def test_edit_file_success(self, handler: ToolHandler, person_dir: Path):
        path = person_dir / "code.py"
        path.write_text("def foo():\n    pass\n", encoding="utf-8")
        result = handler.handle(
            "edit_file",
            {"path": str(path), "old_string": "pass", "new_string": "return 42"},
        )
        assert "Edited" in result
        assert "return 42" in path.read_text(encoding="utf-8")

    def test_edit_file_old_string_not_found(self, handler: ToolHandler, person_dir: Path):
        path = person_dir / "code.py"
        path.write_text("def foo():\n    pass\n", encoding="utf-8")
        result = handler.handle(
            "edit_file",
            {"path": str(path), "old_string": "NOTEXIST", "new_string": "new"},
        )
        assert "old_string not found" in result

    def test_edit_file_ambiguous_match(self, handler: ToolHandler, person_dir: Path):
        path = person_dir / "code.py"
        path.write_text("pass\npass\n", encoding="utf-8")
        result = handler.handle(
            "edit_file",
            {"path": str(path), "old_string": "pass", "new_string": "new"},
        )
        assert "matches 2 locations" in result

    def test_edit_file_not_found(self, handler: ToolHandler, person_dir: Path):
        result = handler.handle(
            "edit_file",
            {"path": str(person_dir / "missing.py"), "old_string": "x", "new_string": "y"},
        )
        assert "File not found" in result


# ── Command execution ─────────────────────────────────────────


class TestExecuteCommand:
    def test_command_denied_without_permission(self, handler: ToolHandler):
        result = handler.handle("execute_command", {"command": "ls"})
        assert "Permission denied" in result

    def test_empty_command_denied(self, handler: ToolHandler):
        result = handler.handle("execute_command", {"command": ""})
        assert "Permission denied" in result

    def test_shell_metachar_rejected(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## コマンド実行\n- ls: OK"
        result = handler.handle("execute_command", {"command": "ls; rm -rf /"})
        assert "metacharacters" in result

    def test_command_allowed(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## コマンド実行\n- echo: OK"
        result = handler.handle("execute_command", {"command": "echo hello"})
        assert "hello" in result

    def test_command_not_in_allowed_list(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## コマンド実行\n- git: OK"
        result = handler.handle("execute_command", {"command": "rm -rf /"})
        assert "Permission denied" in result

    def test_no_explicit_command_list_allows_all(self, handler: ToolHandler, memory: MagicMock):
        # Section exists but no command entries
        memory.read_permissions.return_value = "## コマンド実行\nany command is fine"
        result = handler.handle("execute_command", {"command": "echo hi"})
        assert "hi" in result

    def test_command_timeout(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## コマンド実行\n- sleep: OK"
        result = handler.handle(
            "execute_command", {"command": "sleep 999", "timeout": 1},
        )
        assert "timed out" in result


# ── File permission checks ────────────────────────────────────


class TestFilePermissions:
    def test_own_person_dir_always_allowed(self, handler: ToolHandler, person_dir: Path):
        result = handler._check_file_permission(str(person_dir / "any_file.md"))
        assert result is None

    def test_denied_without_file_section(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "# Some other section"
        result = handler._check_file_permission("/tmp/outside.txt")
        assert "Permission denied" in result

    def test_denied_empty_allowed_dirs(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## ファイル操作\nno paths listed"
        result = handler._check_file_permission("/tmp/outside.txt")
        assert "no allowed paths" in result

    def test_allowed_path_in_whitelist(
        self, handler: ToolHandler, memory: MagicMock, tmp_path: Path,
    ):
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        memory.read_permissions.return_value = f"## ファイル操作\n- {allowed_dir}: OK"
        result = handler._check_file_permission(str(allowed_dir / "file.txt"))
        assert result is None

    def test_denied_path_not_in_whitelist(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## ファイル操作\n- /opt/safe: OK"
        result = handler._check_file_permission("/tmp/not_safe/file.txt")
        assert "Permission denied" in result
        assert "not under any allowed" in result

    def test_file_section_ends_at_next_header(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = (
            "## ファイル操作\n- /opt/safe: OK\n## コマンド実行\n- /opt/also: not a path"
        )
        result = handler._check_file_permission("/opt/also/file.txt")
        assert "Permission denied" in result


# ── Command permission checks ─────────────────────────────────


class TestCommandPermissions:
    def test_empty_command(self, handler: ToolHandler):
        assert "empty command" in handler._check_command_permission("")

    def test_whitespace_only(self, handler: ToolHandler):
        assert "empty command" in handler._check_command_permission("   ")

    def test_metachar_semicolon(self, handler: ToolHandler):
        assert "metacharacters" in handler._check_command_permission("ls; echo hi")

    def test_metachar_pipe(self, handler: ToolHandler):
        assert "metacharacters" in handler._check_command_permission("ls | grep foo")

    def test_metachar_backtick(self, handler: ToolHandler):
        assert "metacharacters" in handler._check_command_permission("echo `whoami`")

    def test_metachar_dollar(self, handler: ToolHandler):
        assert "metacharacters" in handler._check_command_permission("echo $HOME")

    def test_no_command_section(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "nothing relevant"
        assert "not enabled" in handler._check_command_permission("git status")

    def test_invalid_syntax(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## コマンド実行\n- git: OK"
        assert "invalid command syntax" in handler._check_command_permission("git 'unclosed")


# ── Shell metachar regex ──────────────────────────────────────


class TestShellMetacharRe:
    @pytest.mark.parametrize("char", [";", "&", "|", "`", "$", "(", ")", "{", "}"])
    def test_detects_metachar(self, char: str):
        assert _SHELL_METACHAR_RE.search(f"cmd {char} other")

    def test_safe_command(self):
        assert _SHELL_METACHAR_RE.search("git status --short") is None

    def test_safe_command_with_quotes(self):
        assert _SHELL_METACHAR_RE.search("echo 'hello world'") is None
