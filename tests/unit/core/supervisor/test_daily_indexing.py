# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0
"""Tests for daily RAG indexing in ProcessSupervisor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.supervisor._mgr_scheduler import _marker_dir


def _make_supervisor(tmp_path: Path):
    from core.supervisor.manager import ProcessSupervisor

    animas_dir = tmp_path / "animas"
    animas_dir.mkdir(parents=True, exist_ok=True)
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    return ProcessSupervisor(
        animas_dir=animas_dir,
        shared_dir=shared_dir,
        run_dir=run_dir,
    )


def _create_anima_dir(animas_dir: Path, name: str, *, with_knowledge: bool = False) -> None:
    d = animas_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "identity.md").write_text(f"# {name}", encoding="utf-8")
    (d / "status.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    if with_knowledge:
        (d / "knowledge").mkdir(exist_ok=True)
        (d / "knowledge" / "test.md").write_text("# test", encoding="utf-8")


@pytest.mark.asyncio
async def test_daily_indexing_uses_per_anima_vectordb(tmp_path: Path) -> None:
    sup = _make_supervisor(tmp_path)
    _create_anima_dir(sup.animas_dir, "sakura", with_knowledge=True)

    chroma_calls: list[tuple] = []

    def capture_chroma(persist_dir=None, **kwargs):
        chroma_calls.append((persist_dir,))
        store = MagicMock()
        return store

    with (
        patch("core.paths.get_data_dir", return_value=tmp_path),
        patch("core.paths.get_anima_vectordb_dir", side_effect=lambda n: tmp_path / "animas" / n / "vectordb"),
        patch("core.memory.rag.store.ChromaVectorStore", side_effect=capture_chroma),
        patch("core.memory.rag.MemoryIndexer") as mock_indexer_cls,
        patch("core.paths.get_common_knowledge_dir", return_value=tmp_path / "ck"),
        patch("core.paths.get_common_skills_dir", return_value=tmp_path / "cs"),
    ):
        mock_indexer = MagicMock()
        mock_indexer.index_directory = MagicMock(return_value=0)
        mock_indexer.index_conversation_summary = MagicMock(return_value=0)
        mock_indexer_cls.return_value = mock_indexer

        await sup._run_daily_indexing()

    assert len(chroma_calls) >= 1
    assert chroma_calls[0][0] == tmp_path / "animas" / "sakura" / "vectordb"


@pytest.mark.asyncio
async def test_daily_indexing_incremental(tmp_path: Path) -> None:
    sup = _make_supervisor(tmp_path)
    _create_anima_dir(sup.animas_dir, "sakura", with_knowledge=True)

    index_dir_calls: list[tuple] = []

    def capture_index_dir(directory, memory_type, force=False):
        index_dir_calls.append((directory, memory_type, force))
        return 0

    mock_store = MagicMock()
    with (
        patch("core.paths.get_data_dir", return_value=tmp_path),
        patch("core.paths.get_anima_vectordb_dir", side_effect=lambda n: tmp_path / "animas" / n / "vectordb"),
        patch("core.memory.rag.store.ChromaVectorStore", return_value=mock_store),
        patch("core.memory.rag.MemoryIndexer") as mock_indexer_cls,
        patch("core.paths.get_common_knowledge_dir", return_value=tmp_path / "ck"),
        patch("core.paths.get_common_skills_dir", return_value=tmp_path / "cs"),
    ):
        mock_indexer = MagicMock()
        mock_indexer.index_directory = MagicMock(side_effect=capture_index_dir)
        mock_indexer.index_conversation_summary = MagicMock(return_value=0)
        mock_indexer_cls.return_value = mock_indexer

        await sup._run_daily_indexing()

    for _, _, force in index_dir_calls:
        assert force is False


@pytest.mark.asyncio
async def test_daily_indexing_writes_marker(tmp_path: Path) -> None:
    sup = _make_supervisor(tmp_path)
    _create_anima_dir(sup.animas_dir, "sakura")

    mock_store = MagicMock()
    with (
        patch("core.paths.get_data_dir", return_value=tmp_path),
        patch("core.paths.get_anima_vectordb_dir", side_effect=lambda n: tmp_path / "animas" / n / "vectordb"),
        patch("core.memory.rag.store.ChromaVectorStore", return_value=mock_store),
        patch("core.memory.rag.MemoryIndexer") as mock_indexer_cls,
        patch("core.paths.get_common_knowledge_dir", return_value=tmp_path / "ck"),
        patch("core.paths.get_common_skills_dir", return_value=tmp_path / "cs"),
    ):
        mock_indexer = MagicMock()
        mock_indexer.index_directory = MagicMock(return_value=0)
        mock_indexer.index_conversation_summary = MagicMock(return_value=0)
        mock_indexer_cls.return_value = mock_indexer

        await sup._run_daily_indexing()

    marker_path = _marker_dir(sup._get_data_dir()) / "last_daily_indexing"
    assert marker_path.exists()
    assert marker_path.read_text().strip()


@pytest.mark.asyncio
async def test_daily_indexing_skips_on_model_change(tmp_path: Path) -> None:
    sup = _make_supervisor(tmp_path)
    _create_anima_dir(sup.animas_dir, "sakura")

    (tmp_path / "index_meta.json").write_text(json.dumps({"embedding_model": "old-model-name"}), encoding="utf-8")

    chroma_called = False

    def track_chroma(*args, **kwargs):
        nonlocal chroma_called
        chroma_called = True
        return MagicMock()

    with (
        patch("core.paths.get_data_dir", return_value=tmp_path),
        patch(
            "core.memory.rag.singleton.get_embedding_model_name",
            return_value="intfloat/multilingual-e5-small",
        ),
        patch("core.memory.rag.store.ChromaVectorStore", side_effect=track_chroma),
    ):
        await sup._run_daily_indexing()

    assert chroma_called is False
