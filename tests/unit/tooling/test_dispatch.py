"""Tests for core.tooling.dispatch — ExternalToolDispatcher."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import core.tools
from pathlib import Path

from core.tooling.dispatch import ExternalToolDispatcher, _execute, _handle_generate_character_assets
import core.tooling.dispatch as _dispatch_mod


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def empty_dispatcher() -> ExternalToolDispatcher:
    return ExternalToolDispatcher(tool_registry=[])


@pytest.fixture
def dispatcher_with_registry() -> ExternalToolDispatcher:
    return ExternalToolDispatcher(tool_registry=["web_search"])


# ── dispatch() ────────────────────────────────────────────────


class TestDispatch:
    def test_returns_none_when_no_match(self, empty_dispatcher: ExternalToolDispatcher):
        result = empty_dispatcher.dispatch("unknown", {})
        assert result is None

    def test_delegates_to_core_first(self):
        d = ExternalToolDispatcher(tool_registry=["web_search"])
        with patch.object(d, "_dispatch_core", return_value="core result") as mock_core:
            result = d.dispatch("web_search", {"query": "test"})
        assert result == "core result"

    def test_falls_through_to_personal(self):
        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch.object(d, "_dispatch_core", return_value=None), \
             patch.object(d, "_dispatch_personal", return_value="personal result"):
            result = d.dispatch("my_fn", {})
        assert result == "personal result"

    def test_returns_none_when_both_miss(self):
        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch.object(d, "_dispatch_core", return_value=None), \
             patch.object(d, "_dispatch_personal", return_value=None):
            result = d.dispatch("unknown", {})
        assert result is None


# ── _dispatch_core() ──────────────────────────────────────────


class TestDispatchCore:
    def test_empty_registry_returns_none(self, empty_dispatcher: ExternalToolDispatcher):
        result = empty_dispatcher._dispatch_core("web_search", {})
        assert result is None

    def test_tool_not_in_registry(self):
        d = ExternalToolDispatcher(tool_registry=["web_search"])
        with patch.dict(core.tools.TOOL_MODULES, {"slack": "core.tools.slack"}, clear=True):
            result = d._dispatch_core("slack_send", {})
        assert result is None

    def test_dispatches_matching_schema(self):
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [
            {"name": "web_search", "description": "Search"},
        ]

        d = ExternalToolDispatcher(tool_registry=["web_search"])
        with patch.dict(core.tools.TOOL_MODULES, {"web_search": "core.tools.web_search"}, clear=True), \
             patch("importlib.import_module", return_value=mock_mod), \
             patch.object(_dispatch_mod, "_execute", return_value="search result"):
            result = d._dispatch_core("web_search", {"query": "test"})

        assert result == "search result"

    def test_returns_json_for_dict_result(self):
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [{"name": "tool1"}]

        d = ExternalToolDispatcher(tool_registry=["t1"])
        with patch.dict(core.tools.TOOL_MODULES, {"t1": "core.tools.t1"}, clear=True), \
             patch("importlib.import_module", return_value=mock_mod), \
             patch.object(_dispatch_mod, "_execute", return_value={"key": "value"}):
            result = d._dispatch_core("tool1", {})

        assert '"key": "value"' in result

    def test_returns_json_for_list_result(self):
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [{"name": "tool1"}]

        d = ExternalToolDispatcher(tool_registry=["t1"])
        with patch.dict(core.tools.TOOL_MODULES, {"t1": "core.tools.t1"}, clear=True), \
             patch("importlib.import_module", return_value=mock_mod), \
             patch.object(_dispatch_mod, "_execute", return_value=[1, 2, 3]):
            result = d._dispatch_core("tool1", {})

        assert "1" in result
        assert "2" in result

    def test_returns_no_output_for_none(self):
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [{"name": "tool1"}]

        d = ExternalToolDispatcher(tool_registry=["t1"])
        with patch.dict(core.tools.TOOL_MODULES, {"t1": "core.tools.t1"}, clear=True), \
             patch("importlib.import_module", return_value=mock_mod), \
             patch.object(_dispatch_mod, "_execute", return_value=None):
            result = d._dispatch_core("tool1", {})

        assert result == "(no output)"

    def test_handles_module_without_get_tool_schemas(self):
        mock_mod = MagicMock(spec=[])  # No get_tool_schemas

        d = ExternalToolDispatcher(tool_registry=["web_search"])
        with patch.dict(core.tools.TOOL_MODULES, {"web_search": "core.tools.web_search"}, clear=True), \
             patch("importlib.import_module", return_value=mock_mod):
            result = d._dispatch_core("web_search", {})

        assert result is None

    def test_handles_execution_error(self):
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [{"name": "web_search"}]

        d = ExternalToolDispatcher(tool_registry=["web_search"])
        with patch.dict(core.tools.TOOL_MODULES, {"web_search": "core.tools.web_search"}, clear=True), \
             patch("importlib.import_module", return_value=mock_mod), \
             patch.object(_dispatch_mod, "_execute", side_effect=RuntimeError("boom")):
            result = d._dispatch_core("web_search", {})

        assert "Error executing" in result
        assert "boom" in result

    def test_schema_name_not_in_module_schemas(self):
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [{"name": "other_tool"}]

        d = ExternalToolDispatcher(tool_registry=["web_search"])
        with patch.dict(core.tools.TOOL_MODULES, {"web_search": "core.tools.web_search"}, clear=True), \
             patch("importlib.import_module", return_value=mock_mod):
            result = d._dispatch_core("web_search", {})

        assert result is None


# ── _dispatch_personal() ──────────────────────────────────────


class TestDispatchPersonal:
    def test_empty_personal_tools(self, empty_dispatcher: ExternalToolDispatcher):
        result = empty_dispatcher._dispatch_personal("my_fn", {})
        assert result is None

    def test_dispatches_via_module_dispatch(self):
        mock_spec = MagicMock()
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [{"name": "my_fn"}]
        mock_mod.dispatch.return_value = "dispatched result"

        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch("importlib.util.spec_from_file_location", return_value=mock_spec), \
             patch("importlib.util.module_from_spec", return_value=mock_mod):
            result = d._dispatch_personal("my_fn", {"arg": "val"})

        assert result == "dispatched result"

    def test_dispatches_via_function_name(self):
        mock_spec = MagicMock()
        mock_mod = MagicMock(spec=["get_tool_schemas", "my_fn"])
        mock_mod.get_tool_schemas.return_value = [{"name": "my_fn"}]
        mock_mod.my_fn.return_value = "func result"

        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch("importlib.util.spec_from_file_location", return_value=mock_spec), \
             patch("importlib.util.module_from_spec", return_value=mock_mod):
            result = d._dispatch_personal("my_fn", {"arg": "val"})

        assert result == "func result"

    def test_no_handler_returns_error(self):
        mock_spec = MagicMock()
        mock_mod = MagicMock(spec=["get_tool_schemas"])
        mock_mod.get_tool_schemas.return_value = [{"name": "my_fn"}]

        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch("importlib.util.spec_from_file_location", return_value=mock_spec), \
             patch("importlib.util.module_from_spec", return_value=mock_mod):
            result = d._dispatch_personal("my_fn", {})

        assert "no handler" in result

    def test_spec_is_none_skips(self):
        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch("importlib.util.spec_from_file_location", return_value=None):
            result = d._dispatch_personal("my_fn", {})

        assert result is None

    def test_loader_is_none_skips(self):
        mock_spec = MagicMock()
        mock_spec.loader = None

        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch("importlib.util.spec_from_file_location", return_value=mock_spec):
            result = d._dispatch_personal("my_fn", {})

        assert result is None

    def test_schema_name_not_matching(self):
        mock_spec = MagicMock()
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [{"name": "other_fn"}]

        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch("importlib.util.spec_from_file_location", return_value=mock_spec), \
             patch("importlib.util.module_from_spec", return_value=mock_mod):
            result = d._dispatch_personal("my_fn", {})

        assert result is None

    def test_execution_error(self):
        mock_spec = MagicMock()
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [{"name": "my_fn"}]
        mock_mod.dispatch.side_effect = RuntimeError("fail")

        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch("importlib.util.spec_from_file_location", return_value=mock_spec), \
             patch("importlib.util.module_from_spec", return_value=mock_mod):
            result = d._dispatch_personal("my_fn", {})

        assert "Error executing personal tool" in result

    def test_dict_result_serialized(self):
        mock_spec = MagicMock()
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [{"name": "my_fn"}]
        mock_mod.dispatch.return_value = {"status": "ok"}

        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch("importlib.util.spec_from_file_location", return_value=mock_spec), \
             patch("importlib.util.module_from_spec", return_value=mock_mod):
            result = d._dispatch_personal("my_fn", {})

        assert '"status": "ok"' in result

    def test_none_result_returns_no_output(self):
        mock_spec = MagicMock()
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [{"name": "my_fn"}]
        mock_mod.dispatch.return_value = None

        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch("importlib.util.spec_from_file_location", return_value=mock_spec), \
             patch("importlib.util.module_from_spec", return_value=mock_mod):
            result = d._dispatch_personal("my_fn", {})

        assert result == "(no output)"

    def test_module_without_get_tool_schemas(self):
        mock_spec = MagicMock()
        mock_mod = MagicMock(spec=[])  # No get_tool_schemas

        d = ExternalToolDispatcher(
            tool_registry=[],
            personal_tools={"my_tool": "/path/to/tool.py"},
        )
        with patch("importlib.util.spec_from_file_location", return_value=mock_spec), \
             patch("importlib.util.module_from_spec", return_value=mock_mod):
            result = d._dispatch_personal("my_fn", {})

        assert result is None


# ── _execute() ────────────────────────────────────────────────


class TestExecuteFunction:
    def test_web_search(self):
        mod = MagicMock()
        mod.search.return_value = "search results"
        result = _execute(mod, schema_name="web_search", args={"query": "test"})
        assert result == "search results"
        mod.search.assert_called_once_with(query="test")

    def test_x_search(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.search_recent.return_value = "tweets"
        mod.XSearchClient.return_value = mock_client

        result = _execute(mod, schema_name="x_search", args={"query": "test"})
        assert result == "tweets"

    def test_x_user_tweets(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.get_user_tweets.return_value = "user tweets"
        mod.XSearchClient.return_value = mock_client

        result = _execute(mod, schema_name="x_user_tweets", args={"username": "alice"})
        assert result == "user tweets"

    def test_chatwork_send(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.resolve_room_id.return_value = "123"
        mock_client.post_message.return_value = "sent"
        mod.ChatworkClient.return_value = mock_client

        result = _execute(
            mod,
            schema_name="chatwork_send",
            args={"room": "general", "message": "hi"},
        )
        assert result == "sent"

    def test_chatwork_rooms(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.rooms.return_value = [{"name": "general"}]
        mod.ChatworkClient.return_value = mock_client

        result = _execute(mod, schema_name="chatwork_rooms", args={})
        assert result == [{"name": "general"}]

    def test_slack_send(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.resolve_channel.return_value = "C123"
        mock_client.post_message.return_value = "ok"
        mod.SlackClient.return_value = mock_client

        result = _execute(
            mod,
            schema_name="slack_send",
            args={"channel": "general", "message": "hello"},
        )
        assert result == "ok"

    def test_slack_channels(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.channels.return_value = ["general"]
        mod.SlackClient.return_value = mock_client

        result = _execute(mod, schema_name="slack_channels", args={})
        assert result == ["general"]

    def test_gmail_unread(self):
        mod = MagicMock()
        mock_client = MagicMock()
        email = MagicMock()
        email.id = "1"
        email.from_addr = "a@b.com"
        email.subject = "Hi"
        email.snippet = "Hello"
        mock_client.get_unread_emails.return_value = [email]
        mod.GmailClient.return_value = mock_client

        result = _execute(mod, schema_name="gmail_unread", args={})
        assert len(result) == 1
        assert result[0]["subject"] == "Hi"

    def test_gmail_read_body(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.get_email_body.return_value = "email body"
        mod.GmailClient.return_value = mock_client

        result = _execute(mod, schema_name="gmail_read_body", args={"message_id": "1"})
        assert result == "email body"

    def test_gmail_draft(self):
        mod = MagicMock()
        mock_client = MagicMock()
        draft_result = MagicMock(success=True, draft_id="d1", error=None)
        mock_client.create_draft.return_value = draft_result
        mod.GmailClient.return_value = mock_client

        result = _execute(
            mod,
            schema_name="gmail_draft",
            args={"to": "a@b.com", "subject": "Hi", "body": "Hello"},
        )
        assert result["success"] is True

    def test_local_llm_generate(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.generate.return_value = "generated text"
        mod.OllamaClient.return_value = mock_client

        result = _execute(
            mod,
            schema_name="local_llm_generate",
            args={"prompt": "test prompt"},
        )
        assert result == "generated text"

    def test_local_llm_models(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.list_models.return_value = ["model1"]
        mod.OllamaClient.return_value = mock_client

        result = _execute(mod, schema_name="local_llm_models", args={})
        assert result == ["model1"]

    def test_local_llm_status(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.server_status.return_value = {"status": "ok"}
        mod.OllamaClient.return_value = mock_client

        result = _execute(mod, schema_name="local_llm_status", args={})
        assert result["status"] == "ok"

    def test_github_list_issues(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.list_issues.return_value = [{"title": "Bug"}]
        mod.GitHubClient.return_value = mock_client

        result = _execute(mod, schema_name="github_list_issues", args={})
        assert result == [{"title": "Bug"}]

    def test_github_create_issue(self):
        mod = MagicMock()
        mock_client = MagicMock()
        mock_client.create_issue.return_value = {"id": 1}
        mod.GitHubClient.return_value = mock_client

        result = _execute(
            mod,
            schema_name="github_create_issue",
            args={"title": "Bug report"},
        )
        assert result == {"id": 1}

    def test_unknown_schema_raises(self):
        mod = MagicMock()
        with pytest.raises(ValueError, match="No handler"):
            _execute(mod, schema_name="totally_unknown_schema", args={})

    def test_aws_ecs_status(self):
        mod = MagicMock()
        mock_collector = MagicMock()
        mock_collector.get_ecs_status.return_value = {"status": "running"}
        mod.AWSCollector.return_value = mock_collector

        result = _execute(
            mod,
            schema_name="aws_ecs_status",
            args={"cluster": "c1", "service": "s1"},
        )
        assert result == {"status": "running"}

    def test_transcribe_audio(self):
        mod = MagicMock()
        mod.process_audio.return_value = "transcribed text"
        result = _execute(
            mod,
            schema_name="transcribe_audio",
            args={"audio_path": "/tmp/audio.wav"},
        )
        assert result == "transcribed text"


# ── _handle_generate_character_assets() ──────────────────────


class TestHandleGenerateCharacterAssets:
    def test_passes_image_gen_config_to_pipeline(self):
        from core.config.models import AnimaWorksConfig, ImageGenConfig

        mock_config = AnimaWorksConfig(
            image_gen=ImageGenConfig(
                style_prefix="anime, ",
                vibe_strength=0.7,
            )
        )
        mock_mod = MagicMock()
        mock_pipeline = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"fullbody": "/path/to/img.png"}
        mock_pipeline.generate_all.return_value = mock_result
        mock_mod.ImageGenPipeline.return_value = mock_pipeline

        with patch("core.config.models.load_config", return_value=mock_config):
            result = _handle_generate_character_assets(
                mock_mod,
                {"person_dir": "/tmp/test", "prompt": "1girl"},
            )

        # Verify ImageGenPipeline was constructed with the config's image_gen
        call_args = mock_mod.ImageGenPipeline.call_args
        assert call_args[0][0] == Path("/tmp/test")
        assert call_args[1]["config"] is mock_config.image_gen
        assert call_args[1]["config"].style_prefix == "anime, "
        assert call_args[1]["config"].vibe_strength == 0.7
        assert result == {"fullbody": "/path/to/img.png"}

    def test_uses_default_config_when_no_image_gen(self):
        from core.config.models import AnimaWorksConfig, ImageGenConfig

        mock_config = AnimaWorksConfig()  # default config
        mock_mod = MagicMock()
        mock_pipeline = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {}
        mock_pipeline.generate_all.return_value = mock_result
        mock_mod.ImageGenPipeline.return_value = mock_pipeline

        with patch("core.config.models.load_config", return_value=mock_config):
            _handle_generate_character_assets(
                mock_mod,
                {"person_dir": "/tmp/test", "prompt": "1girl"},
            )

        call_args = mock_mod.ImageGenPipeline.call_args
        config_arg = call_args[1]["config"]
        assert isinstance(config_arg, ImageGenConfig)
        assert config_arg.style_reference is None
        assert config_arg.style_prefix == ""
        assert config_arg.vibe_strength == 0.6
