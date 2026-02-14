"""Tests for core.execution.assisted — Mode B: assisted executor."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio

from core.execution.base import ExecutionResult
from core.schemas import ModelConfig
from tests.helpers.mocks import make_litellm_response


# ── litellm sys.modules mock ─────────────────────────────────


def _ensure_litellm_mock():
    """Ensure a mock litellm is in sys.modules."""
    if "litellm" not in sys.modules or not isinstance(sys.modules["litellm"], MagicMock):
        mock_mod = MagicMock()
        mock_mod.acompletion = AsyncMock()
        sys.modules["litellm"] = mock_mod


# ── Helpers ──────────────────────────────────────────────────


def _post_call_nashi() -> str:
    """Post-call response: no knowledge, no send."""
    return "## 知識抽出\nなし\n\n## 返信判定\n返信不要"


def _post_call_knowledge(text: str) -> str:
    """Post-call response: with knowledge, no send."""
    return f"## 知識抽出\n{text}\n\n## 返信判定\n返信不要"


def _post_call_reply(content: str, knowledge: str = "なし") -> str:
    """Post-call response: with reply."""
    return f"## 知識抽出\n{knowledge}\n\n## 返信判定\n返信: {content}"


def _post_call_report(content: str, knowledge: str = "なし") -> str:
    """Post-call response: with report."""
    return f"## 知識抽出\n{knowledge}\n\n## 報告判定\n報告: {content}"


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def model_config() -> ModelConfig:
    return ModelConfig(
        model="openai/gpt-4o",
        api_key="sk-test",
        max_tokens=1024,
    )


@pytest.fixture
def person_dir(tmp_path: Path) -> Path:
    d = tmp_path / "persons" / "test"
    d.mkdir(parents=True)
    for sub in ["episodes", "knowledge", "procedures", "skills", "state"]:
        (d / sub).mkdir(exist_ok=True)
    (d / "identity.md").write_text("# Test Person\nA test person.", encoding="utf-8")
    (d / "injection.md").write_text("Be helpful.", encoding="utf-8")
    return d


@pytest.fixture
def memory(person_dir: Path) -> MagicMock:
    from core.memory import MemoryManager
    m = MagicMock(spec=MemoryManager)
    m.person_dir = person_dir
    m.read_identity.return_value = "# Test Person\nA test person."
    m.read_injection.return_value = "Be helpful."
    m.read_recent_episodes.return_value = "- 10:00 did something"
    m.search_memory_text.return_value = [("knowledge/k1.md", "relevant info")]
    return m


@pytest.fixture
def messenger() -> MagicMock:
    from core.messenger import Messenger
    m = MagicMock(spec=Messenger)
    return m


@pytest.fixture
def executor(
    model_config: ModelConfig,
    person_dir: Path,
    memory: MagicMock,
):
    _ensure_litellm_mock()
    from core.execution.assisted import AssistedExecutor
    return AssistedExecutor(
        model_config=model_config,
        person_dir=person_dir,
        memory=memory,
    )


@pytest.fixture
def executor_with_messenger(
    model_config: ModelConfig,
    person_dir: Path,
    memory: MagicMock,
    messenger: MagicMock,
):
    _ensure_litellm_mock()
    from core.execution.assisted import AssistedExecutor
    return AssistedExecutor(
        model_config=model_config,
        person_dir=person_dir,
        memory=memory,
        messenger=messenger,
    )


# ── _call_llm ─────────────────────────────────────────────────


class TestCallLlm:
    async def test_basic_call(self, executor):
        resp = make_litellm_response(content="LLM response")
        with patch("litellm.acompletion", AsyncMock(return_value=resp)) as mock:
            result = await executor._call_llm(
                [{"role": "user", "content": "hello"}],
            )
        assert result.choices[0].message.content == "LLM response"

    async def test_with_system_prompt(self, executor):
        resp = make_litellm_response(content="response")
        mock = AsyncMock(return_value=resp)
        with patch("litellm.acompletion", mock):
            await executor._call_llm(
                [{"role": "user", "content": "hello"}],
                system="System instructions",
            )
            call_kwargs = mock.call_args
            messages = call_kwargs.kwargs.get("messages", call_kwargs[1].get("messages"))
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == "System instructions"

    async def test_includes_api_key(self, executor):
        resp = make_litellm_response(content="response")
        mock = AsyncMock(return_value=resp)
        with patch("litellm.acompletion", mock):
            await executor._call_llm([{"role": "user", "content": "hello"}])
            call_kwargs = mock.call_args
            assert call_kwargs.kwargs.get("api_key") == "sk-test"

    async def test_includes_api_base(self, person_dir: Path, memory: MagicMock):
        config = ModelConfig(
            model="openai/gpt-4o", api_key="sk-test",
            api_base_url="http://localhost:11434/v1",
        )
        _ensure_litellm_mock()
        from core.execution.assisted import AssistedExecutor
        ex = AssistedExecutor(model_config=config, person_dir=person_dir, memory=memory)
        resp = make_litellm_response(content="response")
        mock = AsyncMock(return_value=resp)
        with patch("litellm.acompletion", mock):
            await ex._call_llm([{"role": "user", "content": "hello"}])
            call_kwargs = mock.call_args
            assert call_kwargs.kwargs.get("api_base") == "http://localhost:11434/v1"


# ── execute() ─────────────────────────────────────────────────


class TestExecute:
    async def test_returns_execution_result(self, executor):
        main_resp = make_litellm_response(content="Main reply")
        extract_resp = make_litellm_response(content=_post_call_nashi())
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            result = await executor.execute("What is the status?")
        assert isinstance(result, ExecutionResult)
        assert result.text == "Main reply"

    async def test_gathers_context(self, executor, memory):
        main_resp = make_litellm_response(content="reply")
        extract_resp = make_litellm_response(content=_post_call_nashi())
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            await executor.execute("Tell me about the project")

        memory.read_identity.assert_called_once()
        memory.read_injection.assert_called_once()
        memory.read_recent_episodes.assert_called_once_with(days=7)

    async def test_records_episode(self, executor, memory):
        main_resp = make_litellm_response(content="reply text")
        extract_resp = make_litellm_response(content=_post_call_nashi())
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            await executor.execute("test prompt")

        memory.append_episode.assert_called_once()
        episode_text = memory.append_episode.call_args[0][0]
        assert "assisted" in episode_text
        assert "test prompt" in episode_text

    async def test_extracts_knowledge(self, executor, memory):
        main_resp = make_litellm_response(content="The API key format is sk-xxx")
        extract_resp = make_litellm_response(
            content=_post_call_knowledge("APIキーの形式はsk-xxxである"),
        )
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            await executor.execute("What's the API key format?")

        memory.write_knowledge.assert_called_once()
        args = memory.write_knowledge.call_args
        assert "APIキーの形式" in args[0][1]

    async def test_skips_knowledge_for_nashi(self, executor, memory):
        main_resp = make_litellm_response(content="Hello")
        extract_resp = make_litellm_response(content=_post_call_nashi())
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            await executor.execute("Hi")

        memory.write_knowledge.assert_not_called()

    async def test_knowledge_extraction_failure_swallowed(self, executor, memory):
        main_resp = make_litellm_response(content="reply")
        mock = AsyncMock(side_effect=[main_resp, RuntimeError("extraction fail")])
        with patch("litellm.acompletion", mock):
            result = await executor.execute("test")

        assert result.text == "reply"

    async def test_keyword_search(self, executor, memory):
        main_resp = make_litellm_response(content="reply")
        extract_resp = make_litellm_response(content=_post_call_nashi())
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            await executor.execute("Tell me about Python programming")

        assert memory.search_memory_text.call_count > 0

    async def test_empty_prompt_no_crash(self, executor, memory):
        memory.search_memory_text.return_value = []
        main_resp = make_litellm_response(content="reply")
        extract_resp = make_litellm_response(content=_post_call_nashi())
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            result = await executor.execute("")
        assert result.text == "reply"

    async def test_no_episodes_no_knowledge(self, executor, memory):
        memory.read_recent_episodes.return_value = ""
        memory.search_memory_text.return_value = []
        main_resp = make_litellm_response(content="reply")
        extract_resp = make_litellm_response(content=_post_call_nashi())
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            result = await executor.execute("hello")
        assert result.text == "reply"


# ── Post-call send judgement ──────────────────────────────────


class TestPostCallSend:
    async def test_auto_reply_on_message_trigger(
        self, executor_with_messenger, messenger,
    ):
        main_resp = make_litellm_response(content="reply")
        extract_resp = make_litellm_response(
            content=_post_call_reply("了解しました、対応します"),
        )
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            await executor_with_messenger.execute(
                "タスクをお願いします", trigger="message:sakura",
            )

        messenger.send.assert_called_once()
        call_kwargs = messenger.send.call_args
        assert call_kwargs.kwargs["to"] == "sakura"
        assert "了解" in call_kwargs.kwargs["content"]

    async def test_no_reply_when_not_needed(
        self, executor_with_messenger, messenger,
    ):
        main_resp = make_litellm_response(content="reply")
        extract_resp = make_litellm_response(content=_post_call_nashi())
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            await executor_with_messenger.execute(
                "お疲れ様でした", trigger="message:sakura",
            )

        messenger.send.assert_not_called()

    async def test_auto_report_on_heartbeat(
        self, person_dir, memory, messenger,
    ):
        config = ModelConfig(
            model="openai/gpt-4o",
            api_key="sk-test",
            max_tokens=1024,
            supervisor="boss",
        )
        _ensure_litellm_mock()
        from core.execution.assisted import AssistedExecutor
        ex = AssistedExecutor(
            model_config=config,
            person_dir=person_dir,
            memory=memory,
            messenger=messenger,
        )
        main_resp = make_litellm_response(content="reply")
        extract_resp = make_litellm_response(
            content=_post_call_report("異常を検知しました"),
        )
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            await ex.execute("heartbeat check", trigger="heartbeat")

        messenger.send.assert_called_once()
        call_kwargs = messenger.send.call_args
        assert call_kwargs.kwargs["to"] == "boss"
        assert "異常" in call_kwargs.kwargs["content"]

    async def test_no_report_without_supervisor(
        self, executor_with_messenger, messenger,
    ):
        """No supervisor → no report even if LLM says so."""
        main_resp = make_litellm_response(content="reply")
        extract_resp = make_litellm_response(
            content=_post_call_report("報告事項あり"),
        )
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            await executor_with_messenger.execute(
                "check", trigger="heartbeat",
            )

        # model_config has no supervisor → send should not be called
        messenger.send.assert_not_called()

    async def test_no_send_without_messenger(self, executor):
        """No messenger → no send even if LLM says reply needed."""
        main_resp = make_litellm_response(content="reply")
        extract_resp = make_litellm_response(
            content=_post_call_reply("返信したい"),
        )
        mock = AsyncMock(side_effect=[main_resp, extract_resp])
        with patch("litellm.acompletion", mock):
            result = await executor.execute(
                "msg", trigger="message:someone",
            )

        # Should not crash, just skip
        assert result.text == "reply"
