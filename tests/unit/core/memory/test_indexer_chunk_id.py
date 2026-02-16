"""Unit tests for MemoryIndexer chunk ID generation and memory_type propagation.

Verifies:
- _make_chunk_id produces IDs without path duplication
- _chunk_by_markdown_headings passes memory_type correctly
- _chunk_by_time_headings passes memory_type correctly
- _chunk_file dispatches memory_type to all chunking strategies
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestChunkIdFormat:
    """Verify chunk IDs do not contain doubled directory paths."""

    @pytest.fixture
    def person_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "test_person"
        d.mkdir()
        for sub in ("knowledge", "episodes", "procedures", "skills"):
            (d / sub).mkdir()
        return d

    def _make_indexer(self, person_dir: Path, prefix: str | None = None):
        from core.memory.rag.indexer import MemoryIndexer

        with patch.object(MemoryIndexer, "_init_embedding_model"):
            return MemoryIndexer(
                MagicMock(),
                person_name=person_dir.name,
                person_dir=person_dir,
                collection_prefix=prefix,
            )

    def test_knowledge_chunk_id(self, person_dir: Path):
        indexer = self._make_indexer(person_dir)
        f = person_dir / "knowledge" / "topic.md"
        f.write_text("x", encoding="utf-8")
        cid = indexer._make_chunk_id(f, "knowledge", 0)
        assert cid == f"{person_dir.name}/knowledge/topic.md#0"

    def test_episodes_chunk_id(self, person_dir: Path):
        indexer = self._make_indexer(person_dir)
        f = person_dir / "episodes" / "2026-02-16.md"
        f.write_text("x", encoding="utf-8")
        cid = indexer._make_chunk_id(f, "episodes", 2)
        assert cid == f"{person_dir.name}/episodes/2026-02-16.md#2"

    def test_shared_common_knowledge_chunk_id(self, person_dir: Path):
        indexer = self._make_indexer(person_dir, prefix="shared")
        ck = person_dir / "common_knowledge"
        ck.mkdir(exist_ok=True)
        f = ck / "guide.md"
        f.write_text("x", encoding="utf-8")
        cid = indexer._make_chunk_id(f, "common_knowledge", 0)
        assert cid == "shared/common_knowledge/guide.md#0"
        assert "common_knowledge/common_knowledge/" not in cid


class TestChunkByMarkdownHeadingsMemoryType:
    """Verify _chunk_by_markdown_headings uses the memory_type parameter."""

    @pytest.fixture
    def person_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "person"
        d.mkdir()
        (d / "knowledge").mkdir()
        (d / "common_knowledge").mkdir()
        return d

    def _make_indexer(self, person_dir: Path, prefix: str | None = None):
        from core.memory.rag.indexer import MemoryIndexer

        with patch.object(MemoryIndexer, "_init_embedding_model"):
            return MemoryIndexer(
                MagicMock(),
                person_name=person_dir.name,
                person_dir=person_dir,
                collection_prefix=prefix,
            )

    def test_memory_type_propagated_to_chunk_ids(self, person_dir: Path):
        """When called with memory_type='common_knowledge', chunk IDs reflect that."""
        indexer = self._make_indexer(person_dir, prefix="shared")
        f = person_dir / "common_knowledge" / "guide.md"
        f.write_text("preamble\n\n## Section A\n\nBody A", encoding="utf-8")

        chunks = indexer._chunk_by_markdown_headings(f, f.read_text(), "common_knowledge")
        assert len(chunks) >= 1
        for chunk in chunks:
            assert "common_knowledge" in chunk.id
            assert chunk.metadata["memory_type"] == "common_knowledge"
            # Must NOT contain 'knowledge/' (that would mean the old hardcoded value leaked)
            assert "/knowledge/" not in chunk.id or "/common_knowledge/" in chunk.id

    def test_memory_type_knowledge(self, person_dir: Path):
        """Standard knowledge type still works correctly."""
        indexer = self._make_indexer(person_dir)
        f = person_dir / "knowledge" / "topic.md"
        f.write_text("intro\n\n## Heading\n\nContent here", encoding="utf-8")

        chunks = indexer._chunk_by_markdown_headings(f, f.read_text(), "knowledge")
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.metadata["memory_type"] == "knowledge"


class TestChunkByTimeHeadingsMemoryType:
    """Verify _chunk_by_time_headings uses the memory_type parameter."""

    @pytest.fixture
    def person_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "person"
        d.mkdir()
        (d / "episodes").mkdir()
        return d

    def _make_indexer(self, person_dir: Path):
        from core.memory.rag.indexer import MemoryIndexer

        with patch.object(MemoryIndexer, "_init_embedding_model"):
            return MemoryIndexer(
                MagicMock(),
                person_name=person_dir.name,
                person_dir=person_dir,
            )

    def test_memory_type_propagated_to_chunk_ids(self, person_dir: Path):
        indexer = self._make_indexer(person_dir)
        f = person_dir / "episodes" / "2026-02-16.md"
        f.write_text(
            "# 2026-02-16\n\n## 09:30 — Morning\n\nDid stuff\n\n## 14:00 — Afternoon\n\nMore stuff",
            encoding="utf-8",
        )

        chunks = indexer._chunk_by_time_headings(f, f.read_text(), "episodes")
        assert len(chunks) == 2
        for chunk in chunks:
            assert chunk.metadata["memory_type"] == "episodes"
            assert "episodes/episodes/" not in chunk.id


class TestChunkFileDispatches:
    """Verify _chunk_file dispatches memory_type to all strategies."""

    @pytest.fixture
    def person_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "person"
        d.mkdir()
        for sub in ("knowledge", "episodes", "procedures"):
            (d / sub).mkdir()
        return d

    def _make_indexer(self, person_dir: Path):
        from core.memory.rag.indexer import MemoryIndexer

        with patch.object(MemoryIndexer, "_init_embedding_model"):
            return MemoryIndexer(
                MagicMock(),
                person_name=person_dir.name,
                person_dir=person_dir,
            )

    def test_common_knowledge_dispatches_with_correct_type(self, person_dir: Path):
        indexer = self._make_indexer(person_dir)
        ck_dir = person_dir / "common_knowledge"
        ck_dir.mkdir(exist_ok=True)
        f = ck_dir / "doc.md"
        content = "preamble\n\n## Section\n\nBody"
        f.write_text(content, encoding="utf-8")

        chunks = indexer._chunk_file(f, content, "common_knowledge")
        for chunk in chunks:
            assert chunk.metadata["memory_type"] == "common_knowledge"

    def test_episodes_dispatches_with_correct_type(self, person_dir: Path):
        indexer = self._make_indexer(person_dir)
        f = person_dir / "episodes" / "2026-02-16.md"
        content = "# Day\n\n## 10:00 — Test\n\nContent"
        f.write_text(content, encoding="utf-8")

        chunks = indexer._chunk_file(f, content, "episodes")
        for chunk in chunks:
            assert chunk.metadata["memory_type"] == "episodes"

    def test_procedures_dispatches_with_correct_type(self, person_dir: Path):
        indexer = self._make_indexer(person_dir)
        f = person_dir / "procedures" / "deploy.md"
        content = "# Deploy procedure\n\nStep 1: do the thing"
        f.write_text(content, encoding="utf-8")

        chunks = indexer._chunk_file(f, content, "procedures")
        assert len(chunks) == 1
        assert chunks[0].metadata["memory_type"] == "procedures"
