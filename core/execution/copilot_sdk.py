from __future__ import annotations

# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0

"""Mode P executor: GitHub Copilot SDK.

Current implementation reuses the Codex SDK execution flow and adapts model
prefix / thread persistence naming for copilot/* models.
"""

from pathlib import Path

from core.execution.codex_sdk import CodexSDKExecutor

__all__ = ["CopilotSDKExecutor", "clear_copilot_thread_ids", "is_copilot_sdk_available"]


def _resolve_copilot_model(model: str) -> str:
    """Strip ``copilot/`` prefix and return a bare model name."""
    if model.startswith("copilot/"):
        return model[len("copilot/") :]
    return model


def is_copilot_sdk_available() -> bool:
    """Return True when ``github_copilot_sdk`` is importable."""
    try:
        import github_copilot_sdk  # noqa: F401

        return True
    except Exception:
        return False


def _thread_id_path(anima_dir: Path, session_type: str, chat_thread_id: str = "default") -> Path:
    base = anima_dir / "shortterm" / session_type
    if chat_thread_id != "default":
        return base / chat_thread_id / "copilot_thread_id.txt"
    return base / "copilot_thread_id.txt"


def _save_thread_id(anima_dir: Path, thread_id: str, session_type: str, chat_thread_id: str = "default") -> None:
    p = _thread_id_path(anima_dir, session_type, chat_thread_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(thread_id, encoding="utf-8")


def _load_thread_id(anima_dir: Path, session_type: str, chat_thread_id: str = "default") -> str | None:
    p = _thread_id_path(anima_dir, session_type, chat_thread_id)
    if p.is_file():
        tid = p.read_text(encoding="utf-8").strip()
        return tid or None
    return None


def _clear_thread_id(anima_dir: Path, session_type: str, chat_thread_id: str = "default") -> None:
    p = _thread_id_path(anima_dir, session_type, chat_thread_id)
    p.unlink(missing_ok=True)


def clear_copilot_thread_ids(anima_dir: Path, chat_thread_id: str = "default") -> None:
    """Clear all persisted Copilot thread IDs (both chat and heartbeat)."""
    for st in ("chat", "heartbeat"):
        _clear_thread_id(anima_dir, st, chat_thread_id)


class CopilotSDKExecutor(CodexSDKExecutor):
    """Mode P executor built on Codex-style SDK orchestration."""

    def _write_codex_config(self, system_prompt: str) -> None:
        original_model = self._model_config.model
        remapped = self._model_config.model
        if original_model.startswith("copilot/"):
            remapped = f"codex/{_resolve_copilot_model(original_model)}"
            self._model_config.model = remapped
        try:
            super()._write_codex_config(system_prompt)
        finally:
            self._model_config.model = original_model

    def _create_codex_client(self):
        try:
            import github_copilot_sdk  # noqa: F401
        except ModuleNotFoundError as e:
            raise ImportError("github_copilot_sdk is required for Mode P (install github-copilot-sdk).") from e
        return super()._create_codex_client()

    def _start_or_resume_thread(self, codex, thread_id: str | None, session_type: str):
        if thread_id:
            try:
                return codex.resume_thread(thread_id)
            except Exception:
                pass

        thread = codex.start_thread()
        thread_id = getattr(thread, "id", None) or getattr(thread, "thread_id", None)
        if thread_id:
            _save_thread_id(self._anima_dir, str(thread_id), session_type, self._chat_thread_id)
        return thread

    def _load_thread_for_session(self, session_type: str):
        return _load_thread_id(self._anima_dir, session_type, self._chat_thread_id)
