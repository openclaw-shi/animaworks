"""Tests for core.tooling.handler — ToolHandler permission and dispatch."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.tooling.handler import ToolHandler, _SHELL_METACHAR_RE, _error_result


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

    def test_read_memory_file_common_knowledge_prefix(
        self, handler: ToolHandler, tmp_path: Path,
    ):
        """read_memory_file with common_knowledge/ prefix resolves to shared dir."""
        ck_dir = tmp_path / "ck"
        ck_dir.mkdir()
        (ck_dir / "policy.md").write_text("shared content", encoding="utf-8")
        with patch(
            "core.paths.get_common_knowledge_dir",
            return_value=ck_dir,
        ):
            result = handler.handle(
                "read_memory_file", {"path": "common_knowledge/policy.md"},
            )
        assert result == "shared content"

    def test_read_memory_file_common_knowledge_not_found(
        self, handler: ToolHandler, tmp_path: Path,
    ):
        """read_memory_file with common_knowledge/ prefix for missing file."""
        ck_dir = tmp_path / "ck_empty"
        ck_dir.mkdir()
        with patch(
            "core.paths.get_common_knowledge_dir",
            return_value=ck_dir,
        ):
            result = handler.handle(
                "read_memory_file", {"path": "common_knowledge/missing.md"},
            )
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
        parsed = json.loads(result)
        assert parsed["error_type"] == "FileNotFound"

    def test_read_file_not_a_file(self, handler: ToolHandler, person_dir: Path):
        result = handler.handle("read_file", {"path": str(person_dir)})
        parsed = json.loads(result)
        assert parsed["error_type"] == "InvalidArguments"

    def test_read_file_truncated_at_100k(self, handler: ToolHandler, person_dir: Path):
        big_content = "x" * 200_000
        (person_dir / "big.txt").write_text(big_content, encoding="utf-8")
        result = handler.handle("read_file", {"path": str(person_dir / "big.txt")})
        assert len(result) == 100_000

    def test_read_file_permission_denied(self, handler: ToolHandler):
        result = handler.handle("read_file", {"path": "/etc/passwd"})
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"

    def test_write_file_in_person_dir(self, handler: ToolHandler, person_dir: Path):
        path = person_dir / "output.txt"
        result = handler.handle("write_file", {"path": str(path), "content": "data"})
        assert "Written to" in result
        assert path.read_text(encoding="utf-8") == "data"

    def test_write_file_permission_denied(self, handler: ToolHandler):
        result = handler.handle("write_file", {"path": "/etc/no", "content": "data"})
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"

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
        parsed = json.loads(result)
        assert parsed["error_type"] == "StringNotFound"

    def test_edit_file_ambiguous_match(self, handler: ToolHandler, person_dir: Path):
        path = person_dir / "code.py"
        path.write_text("pass\npass\n", encoding="utf-8")
        result = handler.handle(
            "edit_file",
            {"path": str(path), "old_string": "pass", "new_string": "new"},
        )
        parsed = json.loads(result)
        assert parsed["error_type"] == "AmbiguousMatch"
        assert parsed["context"]["match_count"] == 2

    def test_edit_file_not_found(self, handler: ToolHandler, person_dir: Path):
        result = handler.handle(
            "edit_file",
            {"path": str(person_dir / "missing.py"), "old_string": "x", "new_string": "y"},
        )
        parsed = json.loads(result)
        assert parsed["error_type"] == "FileNotFound"


# ── Command execution ─────────────────────────────────────────


class TestExecuteCommand:
    def test_command_denied_without_permission(self, handler: ToolHandler):
        result = handler.handle("execute_command", {"command": "ls"})
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"

    def test_empty_command_denied(self, handler: ToolHandler):
        result = handler.handle("execute_command", {"command": ""})
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"

    def test_shell_metachar_rejected(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## コマンド実行\n- ls: OK"
        result = handler.handle("execute_command", {"command": "ls; rm -rf /"})
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"
        assert "metacharacters" in parsed["message"]

    def test_command_allowed(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## コマンド実行\n- echo: OK"
        result = handler.handle("execute_command", {"command": "echo hello"})
        assert "hello" in result

    def test_command_not_in_allowed_list(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## コマンド実行\n- git: OK"
        result = handler.handle("execute_command", {"command": "rm -rf /"})
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"

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
        parsed = json.loads(result)
        assert parsed["error_type"] == "Timeout"


# ── File permission checks ────────────────────────────────────


class TestFilePermissions:
    def test_own_person_dir_always_allowed(self, handler: ToolHandler, person_dir: Path):
        result = handler._check_file_permission(str(person_dir / "any_file.md"))
        assert result is None

    def test_denied_without_file_section(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "# Some other section"
        result = handler._check_file_permission("/tmp/outside.txt")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"

    def test_denied_empty_allowed_dirs(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## ファイル操作\nno paths listed"
        result = handler._check_file_permission("/tmp/outside.txt")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"

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
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"
        assert "not under any allowed" in parsed["message"]

    def test_file_section_ends_at_next_header(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = (
            "## ファイル操作\n- /opt/safe: OK\n## コマンド実行\n- /opt/also: not a path"
        )
        result = handler._check_file_permission("/opt/also/file.txt")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"


# ── Command permission checks ─────────────────────────────────


class TestCommandPermissions:
    def test_empty_command(self, handler: ToolHandler):
        result = handler._check_command_permission("")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"
        assert "Empty" in parsed["message"]

    def test_whitespace_only(self, handler: ToolHandler):
        result = handler._check_command_permission("   ")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"
        assert "Empty" in parsed["message"]

    def test_metachar_semicolon(self, handler: ToolHandler):
        result = handler._check_command_permission("ls; echo hi")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"
        assert "metacharacters" in parsed["message"]

    def test_metachar_pipe(self, handler: ToolHandler):
        result = handler._check_command_permission("ls | grep foo")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"
        assert "metacharacters" in parsed["message"]

    def test_metachar_backtick(self, handler: ToolHandler):
        result = handler._check_command_permission("echo `whoami`")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"
        assert "metacharacters" in parsed["message"]

    def test_metachar_dollar(self, handler: ToolHandler):
        result = handler._check_command_permission("echo $HOME")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"
        assert "metacharacters" in parsed["message"]

    def test_no_command_section(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "nothing relevant"
        result = handler._check_command_permission("git status")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"
        assert "not enabled" in parsed["message"]

    def test_invalid_syntax(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## コマンド実行\n- git: OK"
        result = handler._check_command_permission("git 'unclosed")
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"
        assert "Invalid command syntax" in parsed["message"]


# ── Shell metachar regex ──────────────────────────────────────


class TestShellMetacharRe:
    @pytest.mark.parametrize("char", [";", "&", "|", "`", "$", "(", ")", "{", "}"])
    def test_detects_metachar(self, char: str):
        assert _SHELL_METACHAR_RE.search(f"cmd {char} other")

    def test_safe_command(self):
        assert _SHELL_METACHAR_RE.search("git status --short") is None

    def test_safe_command_with_quotes(self):
        assert _SHELL_METACHAR_RE.search("echo 'hello world'") is None


# ── _error_result ────────────────────────────────────────────


class TestErrorResult:
    def test_basic_error(self):
        result = _error_result("TestError", "Something went wrong")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error_type"] == "TestError"
        assert parsed["message"] == "Something went wrong"
        assert "context" not in parsed
        assert "suggestion" not in parsed

    def test_with_suggestion(self):
        result = _error_result("FileNotFound", "not found", suggestion="Use list_directory")
        parsed = json.loads(result)
        assert parsed["suggestion"] == "Use list_directory"

    def test_with_context(self):
        result = _error_result("AmbiguousMatch", "matches 3", context={"match_count": 3})
        parsed = json.loads(result)
        assert parsed["context"]["match_count"] == 3

    def test_with_all_fields(self):
        result = _error_result(
            "PermissionDenied", "denied",
            context={"allowed_dirs": ["/tmp"]},
            suggestion="Check permissions",
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["context"]["allowed_dirs"] == ["/tmp"]
        assert parsed["suggestion"] == "Check permissions"


# ── search_code handler ──────────────────────────────────────


class TestSearchCode:
    def test_search_code_basic(self, handler: ToolHandler, person_dir: Path):
        (person_dir / "test.py").write_text("def hello():\n    return 42\n", encoding="utf-8")
        result = handler.handle("search_code", {"pattern": "hello"})
        assert "test.py:1" in result
        assert "def hello" in result

    def test_search_code_no_matches(self, handler: ToolHandler, person_dir: Path):
        (person_dir / "test.py").write_text("def foo():\n    pass\n", encoding="utf-8")
        result = handler.handle("search_code", {"pattern": "nonexistent"})
        assert "No matches" in result

    def test_search_code_with_glob(self, handler: ToolHandler, person_dir: Path):
        (person_dir / "test.py").write_text("hello\n", encoding="utf-8")
        (person_dir / "test.md").write_text("hello\n", encoding="utf-8")
        result = handler.handle("search_code", {"pattern": "hello", "glob": "*.py"})
        assert "test.py" in result
        # md file should not be included
        assert "test.md" not in result

    def test_search_code_invalid_regex(self, handler: ToolHandler):
        result = handler.handle("search_code", {"pattern": "[invalid"})
        parsed = json.loads(result)
        assert parsed["error_type"] == "InvalidArguments"

    def test_search_code_empty_pattern(self, handler: ToolHandler):
        result = handler.handle("search_code", {"pattern": ""})
        parsed = json.loads(result)
        assert parsed["error_type"] == "InvalidArguments"

    def test_search_code_permission_denied(self, handler: ToolHandler):
        result = handler.handle("search_code", {"pattern": "test", "path": "/etc"})
        assert "error" in result.lower() or "permission" in result.lower()


# ── list_directory handler ───────────────────────────────────


class TestListDirectory:
    def test_list_directory_basic(self, handler: ToolHandler, person_dir: Path):
        (person_dir / "file1.txt").write_text("a", encoding="utf-8")
        (person_dir / "file2.txt").write_text("b", encoding="utf-8")
        (person_dir / "subdir").mkdir()
        result = handler.handle("list_directory", {})
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "subdir/" in result

    def test_list_directory_with_pattern(self, handler: ToolHandler, person_dir: Path):
        (person_dir / "test.py").write_text("", encoding="utf-8")
        (person_dir / "test.md").write_text("", encoding="utf-8")
        result = handler.handle("list_directory", {"pattern": "*.py"})
        assert "test.py" in result
        assert "test.md" not in result

    def test_list_directory_not_found(self, handler: ToolHandler, person_dir: Path):
        result = handler.handle("list_directory", {"path": str(person_dir / "nonexistent")})
        parsed = json.loads(result)
        assert parsed["error_type"] == "FileNotFound"

    def test_list_directory_not_a_dir(self, handler: ToolHandler, person_dir: Path):
        (person_dir / "file.txt").write_text("x", encoding="utf-8")
        result = handler.handle("list_directory", {"path": str(person_dir / "file.txt")})
        parsed = json.loads(result)
        assert parsed["error_type"] == "InvalidArguments"

    def test_list_directory_empty(self, handler: ToolHandler, person_dir: Path):
        empty_dir = person_dir / "empty"
        empty_dir.mkdir()
        result = handler.handle("list_directory", {"path": str(empty_dir)})
        assert "empty" in result.lower()


# ── Structured errors in existing handlers ───────────────────


class TestStructuredErrors:
    def test_read_file_not_found_structured(self, handler: ToolHandler, person_dir: Path):
        result = handler.handle("read_file", {"path": str(person_dir / "missing.txt")})
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error_type"] == "FileNotFound"

    def test_edit_file_string_not_found_structured(self, handler: ToolHandler, person_dir: Path):
        path = person_dir / "code.py"
        path.write_text("def foo():\n    pass\n", encoding="utf-8")
        result = handler.handle(
            "edit_file",
            {"path": str(path), "old_string": "NOTEXIST", "new_string": "new"},
        )
        parsed = json.loads(result)
        assert parsed["error_type"] == "StringNotFound"
        assert "suggestion" in parsed

    def test_edit_file_ambiguous_structured(self, handler: ToolHandler, person_dir: Path):
        path = person_dir / "code.py"
        path.write_text("pass\npass\n", encoding="utf-8")
        result = handler.handle(
            "edit_file",
            {"path": str(path), "old_string": "pass", "new_string": "new"},
        )
        parsed = json.loads(result)
        assert parsed["error_type"] == "AmbiguousMatch"
        assert parsed["context"]["match_count"] == 2

    def test_command_timeout_structured(self, handler: ToolHandler, memory: MagicMock):
        memory.read_permissions.return_value = "## コマンド実行\n- sleep: OK"
        result = handler.handle(
            "execute_command", {"command": "sleep 999", "timeout": 1},
        )
        parsed = json.loads(result)
        assert parsed["error_type"] == "Timeout"

    def test_permission_denied_structured(self, handler: ToolHandler):
        result = handler.handle("read_file", {"path": "/etc/passwd"})
        parsed = json.loads(result)
        assert parsed["error_type"] == "PermissionDenied"


# ── Schedule changed callback ────────────────────────────────


class TestScheduleChangedCallback:
    def test_on_schedule_changed_property(self, handler: ToolHandler):
        assert handler.on_schedule_changed is None
        fn = MagicMock()
        handler.on_schedule_changed = fn
        assert handler.on_schedule_changed is fn

    def test_write_heartbeat_triggers_callback(
        self, person_dir: Path, memory: MagicMock,
    ):
        callback = MagicMock()
        h = ToolHandler(
            person_dir=person_dir,
            memory=memory,
            on_schedule_changed=callback,
        )
        h.handle("write_memory_file", {"path": "heartbeat.md", "content": "new config"})
        callback.assert_called_once_with("test-person")

    def test_write_cron_triggers_callback(
        self, person_dir: Path, memory: MagicMock,
    ):
        callback = MagicMock()
        h = ToolHandler(
            person_dir=person_dir,
            memory=memory,
            on_schedule_changed=callback,
        )
        h.handle("write_memory_file", {"path": "cron.md", "content": "new cron"})
        callback.assert_called_once_with("test-person")

    def test_write_other_file_does_not_trigger_callback(
        self, person_dir: Path, memory: MagicMock,
    ):
        callback = MagicMock()
        h = ToolHandler(
            person_dir=person_dir,
            memory=memory,
            on_schedule_changed=callback,
        )
        h.handle("write_memory_file", {"path": "knowledge/note.md", "content": "note"})
        callback.assert_not_called()

    def test_callback_error_does_not_break_write(
        self, person_dir: Path, memory: MagicMock,
    ):
        callback = MagicMock(side_effect=RuntimeError("reload failed"))
        h = ToolHandler(
            person_dir=person_dir,
            memory=memory,
            on_schedule_changed=callback,
        )
        result = h.handle("write_memory_file", {"path": "heartbeat.md", "content": "cfg"})
        assert "Written to" in result
        # File should still be written despite callback error
        assert (person_dir / "heartbeat.md").read_text(encoding="utf-8") == "cfg"

    def test_no_callback_set_does_not_error(self, handler: ToolHandler, person_dir: Path):
        # handler has no on_schedule_changed set (default None)
        result = handler.handle("write_memory_file", {"path": "heartbeat.md", "content": "cfg"})
        assert "Written to" in result
