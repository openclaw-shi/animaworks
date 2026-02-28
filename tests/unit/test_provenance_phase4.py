from __future__ import annotations

# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for provenance Phase 4: RAG chunk origin metadata + Channel C trust separation."""

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.execution._sanitize import (
    ORIGIN_ANIMA,
    ORIGIN_CONSOLIDATION,
    ORIGIN_EXTERNAL_PLATFORM,
    ORIGIN_EXTERNAL_WEB,
    ORIGIN_HUMAN,
    ORIGIN_SYSTEM,
    ORIGIN_UNKNOWN,
    resolve_trust,
)
from core.memory.priming import PrimingEngine, PrimingResult, format_priming_section


# ── MemoryIndexer._extract_metadata with origin ───────────────


class TestIndexerOriginMetadata:
    """MemoryIndexer stores origin in chunk metadata."""

    @pytest.fixture
    def anima_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "animas" / "test-anima"
        d.mkdir(parents=True)
        (d / "knowledge").mkdir()
        (d / "episodes").mkdir()
        return d

    @pytest.fixture
    def indexer(self, anima_dir: Path):
        from core.memory.rag.indexer import MemoryIndexer

        mock_store = MagicMock()
        mock_model = MagicMock()
        mock_model.encode = MagicMock(return_value=[
            MagicMock(tolist=MagicMock(return_value=[0.1] * 384))
        ])

        return MemoryIndexer(
            mock_store, "test-anima", anima_dir,
            embedding_model=mock_model,
        )

    def test_extract_metadata_without_origin(self, indexer, anima_dir: Path) -> None:
        """When origin is empty, metadata should not contain 'origin' key."""
        test_file = anima_dir / "knowledge" / "test.md"
        test_file.write_text("# Test\n\nSome content here.", encoding="utf-8")

        metadata = indexer._extract_metadata(
            test_file, "Some content", "knowledge", 0, 1,
        )
        assert "origin" not in metadata

    def test_extract_metadata_with_origin(self, indexer, anima_dir: Path) -> None:
        """When origin is provided, it's stored in metadata."""
        test_file = anima_dir / "knowledge" / "test.md"
        test_file.write_text("# Test\n\nSome content here.", encoding="utf-8")

        metadata = indexer._extract_metadata(
            test_file, "Some content", "knowledge", 0, 1,
            origin="consolidation",
        )
        assert metadata["origin"] == "consolidation"

    def test_extract_metadata_external_platform_origin(self, indexer, anima_dir: Path) -> None:
        test_file = anima_dir / "episodes" / "2026-02-28.md"
        test_file.write_text("# Episodes\n\nSome episode.", encoding="utf-8")

        metadata = indexer._extract_metadata(
            test_file, "Some episode content", "episodes", 0, 1,
            origin="external_platform",
        )
        assert metadata["origin"] == "external_platform"

    def test_index_file_passes_origin_to_chunks(self, indexer, anima_dir: Path) -> None:
        """index_file(origin=...) propagates to chunk metadata."""
        test_file = anima_dir / "knowledge" / "test.md"
        test_file.write_text(
            "# Test Knowledge\n\nThis is important knowledge content for testing.",
            encoding="utf-8",
        )

        indexer.vector_store.create_collection = MagicMock()
        indexer.vector_store.upsert = MagicMock()

        with patch("core.memory.rag.singleton.get_embedding_dimension", return_value=384):
            indexer.index_file(test_file, "knowledge", origin="consolidation", force=True)

        assert indexer.vector_store.upsert.called
        call_args = indexer.vector_store.upsert.call_args
        documents = call_args[0][1]
        assert len(documents) > 0
        for doc in documents:
            assert doc.metadata.get("origin") == "consolidation"

    def test_index_file_no_origin_no_metadata_key(self, indexer, anima_dir: Path) -> None:
        """index_file without origin does not add origin to metadata."""
        test_file = anima_dir / "knowledge" / "test2.md"
        test_file.write_text(
            "# Test Knowledge 2\n\nThis is knowledge content without origin.",
            encoding="utf-8",
        )

        indexer.vector_store.create_collection = MagicMock()
        indexer.vector_store.upsert = MagicMock()

        with patch("core.memory.rag.singleton.get_embedding_dimension", return_value=384):
            indexer.index_file(test_file, "knowledge", force=True)

        call_args = indexer.vector_store.upsert.call_args
        documents = call_args[0][1]
        for doc in documents:
            assert "origin" not in doc.metadata

    def test_chunk_by_time_headings_with_origin(self, indexer, anima_dir: Path) -> None:
        """Episode chunking by time headings preserves origin."""
        test_file = anima_dir / "episodes" / "2026-02-28.md"
        content = (
            "# 2026-02-28\n\n"
            "## 10:00 — Morning\n\nDid some work.\n\n"
            "## 14:00 — Afternoon\n\nMore work.\n"
        )
        test_file.write_text(content, encoding="utf-8")

        chunks = indexer._chunk_by_time_headings(
            test_file, content, "episodes", origin="external_platform",
        )
        for chunk in chunks:
            assert chunk.metadata.get("origin") == "external_platform"

    def test_chunk_whole_file_with_origin(self, indexer, anima_dir: Path) -> None:
        """Whole-file chunking preserves origin."""
        test_file = anima_dir / "knowledge" / "proc.md"
        content = "# Procedure\n\nStep 1: Do this."
        test_file.write_text(content, encoding="utf-8")

        chunks = indexer._chunk_whole_file(
            test_file, content, "procedures", origin="system",
        )
        assert len(chunks) == 1
        assert chunks[0].metadata.get("origin") == "system"


# ── MemoryManager.append_episode with origin ──────────────────


class TestMemoryManagerOrigin:
    """MemoryManager passes origin to RAG indexer."""

    @pytest.fixture
    def anima_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "animas" / "test-anima"
        for sub in ("episodes", "knowledge", "procedures", "skills", "state"):
            (d / sub).mkdir(parents=True)
        return d

    @pytest.fixture
    def mm(self, anima_dir: Path, tmp_path: Path):
        from core.memory.manager import MemoryManager

        with (
            patch("core.memory.manager.get_common_knowledge_dir", return_value=tmp_path / "ck"),
            patch("core.memory.manager.get_common_skills_dir", return_value=tmp_path / "cs"),
            patch("core.memory.manager.get_company_dir", return_value=tmp_path / "co"),
            patch("core.memory.manager.get_shared_dir", return_value=tmp_path / "sh"),
        ):
            (tmp_path / "ck").mkdir(exist_ok=True)
            (tmp_path / "cs").mkdir(exist_ok=True)
            (tmp_path / "co").mkdir(exist_ok=True)
            (tmp_path / "sh").mkdir(exist_ok=True)
            mgr = MemoryManager(anima_dir)
            mgr._rag.index_file = MagicMock()
            return mgr

    def test_append_episode_without_origin(self, mm) -> None:
        mm.append_episode("## 10:00 — Test\n\nContent.\n")
        mm._rag.index_file.assert_called_once()
        _, kwargs = mm._rag.index_file.call_args
        assert kwargs.get("origin", "") == ""

    def test_append_episode_with_origin(self, mm) -> None:
        mm.append_episode("## 10:00 — Slack msg\n\nContent.\n", origin="external_platform")
        mm._rag.index_file.assert_called_once()
        _, kwargs = mm._rag.index_file.call_args
        assert kwargs["origin"] == "external_platform"

    def test_write_knowledge_with_origin(self, mm) -> None:
        mm.write_knowledge("test-topic", "# Test\n\nKnowledge content.", origin="consolidation")
        mm._rag.index_file.assert_called_once()
        _, kwargs = mm._rag.index_file.call_args
        assert kwargs["origin"] == "consolidation"

    def test_write_knowledge_without_origin(self, mm) -> None:
        mm.write_knowledge("test-topic", "# Test\n\nKnowledge content.")
        mm._rag.index_file.assert_called_once()
        _, kwargs = mm._rag.index_file.call_args
        assert kwargs.get("origin", "") == ""


# ── RAGMemorySearch.index_file with origin ────────────────────


class TestRAGSearchOriginProxy:
    """RAGMemorySearch.index_file passes origin to underlying indexer."""

    def test_index_file_passes_origin(self, tmp_path: Path) -> None:
        from core.memory.rag_search import RAGMemorySearch

        rag = RAGMemorySearch(tmp_path, tmp_path / "ck", tmp_path / "cs")
        mock_indexer = MagicMock()
        rag._indexer = mock_indexer
        rag._indexer_initialized = True

        test_file = tmp_path / "test.md"
        test_file.write_text("content", encoding="utf-8")

        rag.index_file(test_file, "episodes", origin="external_platform")
        mock_indexer.index_file.assert_called_once_with(
            test_file, "episodes", origin="external_platform",
        )

    def test_index_file_no_origin(self, tmp_path: Path) -> None:
        from core.memory.rag_search import RAGMemorySearch

        rag = RAGMemorySearch(tmp_path, tmp_path / "ck", tmp_path / "cs")
        mock_indexer = MagicMock()
        rag._indexer = mock_indexer
        rag._indexer_initialized = True

        test_file = tmp_path / "test.md"
        test_file.write_text("content", encoding="utf-8")

        rag.index_file(test_file, "knowledge")
        mock_indexer.index_file.assert_called_once_with(
            test_file, "knowledge", origin="",
        )


# ── PrimingResult with related_knowledge_untrusted ────────────


class TestPrimingResultUntrusted:
    """PrimingResult.related_knowledge_untrusted field."""

    def test_default_untrusted_is_empty(self) -> None:
        r = PrimingResult()
        assert r.related_knowledge_untrusted == ""

    def test_is_empty_considers_untrusted(self) -> None:
        r = PrimingResult(related_knowledge_untrusted="some untrusted data")
        assert not r.is_empty()

    def test_total_chars_includes_untrusted(self) -> None:
        r = PrimingResult(
            related_knowledge="trusted",
            related_knowledge_untrusted="untrusted content",
        )
        assert r.total_chars() == len("trusted") + len("untrusted content")

    def test_backward_compat_no_untrusted(self) -> None:
        r = PrimingResult(
            sender_profile="profile",
            related_knowledge="knowledge",
        )
        assert r.related_knowledge_untrusted == ""
        assert r.is_empty() is False


# ── Channel C trust separation ────────────────────────────────


@dataclass
class FakeSearchResult:
    """Mock search result for testing Channel C."""

    doc_id: str = ""
    content: str = ""
    score: float = 0.9
    metadata: dict = field(default_factory=dict)


class TestChannelCTrustSeparation:
    """_channel_c_related_knowledge separates results by trust."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> PrimingEngine:
        anima_dir = tmp_path / "animas" / "test-anima"
        (anima_dir / "knowledge").mkdir(parents=True)
        (anima_dir / "episodes").mkdir(parents=True)
        engine = PrimingEngine(anima_dir, tmp_path / "shared")
        return engine

    def _make_retriever(self, results: list):
        mock_retriever = MagicMock()
        mock_retriever.search = MagicMock(return_value=results)
        mock_retriever.record_access = MagicMock()
        return mock_retriever

    @pytest.mark.asyncio
    async def test_all_trusted_results(self, engine: PrimingEngine) -> None:
        """All results with consolidation origin → all in medium bucket."""
        results = [
            FakeSearchResult(
                content="Trusted knowledge",
                score=0.95,
                metadata={"anima": "test-anima", "origin": "consolidation"},
            ),
        ]
        engine._retriever = self._make_retriever(results)
        engine._retriever_initialized = True

        medium, untrusted = await engine._channel_c_related_knowledge(["test"])
        assert "Trusted knowledge" in medium
        assert untrusted == ""

    @pytest.mark.asyncio
    async def test_all_untrusted_results(self, engine: PrimingEngine) -> None:
        """All results with external origin → all in untrusted bucket."""
        results = [
            FakeSearchResult(
                content="External data",
                score=0.90,
                metadata={"anima": "test-anima", "origin": "external_platform"},
            ),
        ]
        engine._retriever = self._make_retriever(results)
        engine._retriever_initialized = True

        medium, untrusted = await engine._channel_c_related_knowledge(["test"])
        assert medium == ""
        assert "External data" in untrusted

    @pytest.mark.asyncio
    async def test_mixed_trust_results(self, engine: PrimingEngine) -> None:
        """Mixed origins → split between medium and untrusted."""
        results = [
            FakeSearchResult(
                content="Consolidated knowledge",
                score=0.95,
                metadata={"anima": "test-anima", "origin": "consolidation"},
            ),
            FakeSearchResult(
                content="External data from Slack",
                score=0.85,
                metadata={"anima": "test-anima", "origin": "external_platform"},
            ),
        ]
        engine._retriever = self._make_retriever(results)
        engine._retriever_initialized = True

        medium, untrusted = await engine._channel_c_related_knowledge(["test"])
        assert "Consolidated knowledge" in medium
        assert "External data from Slack" in untrusted

    @pytest.mark.asyncio
    async def test_missing_origin_treated_as_untrusted(self, engine: PrimingEngine) -> None:
        """Results without origin metadata → ORIGIN_UNKNOWN → untrusted."""
        results = [
            FakeSearchResult(
                content="Legacy chunk without origin",
                score=0.90,
                metadata={"anima": "test-anima"},
            ),
        ]
        engine._retriever = self._make_retriever(results)
        engine._retriever_initialized = True

        medium, untrusted = await engine._channel_c_related_knowledge(["test"])
        assert medium == ""
        assert "Legacy chunk without origin" in untrusted

    @pytest.mark.asyncio
    async def test_system_origin_is_trusted(self, engine: PrimingEngine) -> None:
        """System origin → trusted → goes to medium bucket."""
        results = [
            FakeSearchResult(
                content="System knowledge",
                score=0.90,
                metadata={"anima": "test-anima", "origin": "system"},
            ),
        ]
        engine._retriever = self._make_retriever(results)
        engine._retriever_initialized = True

        medium, untrusted = await engine._channel_c_related_knowledge(["test"])
        assert "System knowledge" in medium
        assert untrusted == ""

    @pytest.mark.asyncio
    async def test_human_origin_is_medium(self, engine: PrimingEngine) -> None:
        """Human origin → medium trust → goes to medium bucket."""
        results = [
            FakeSearchResult(
                content="Human-provided knowledge",
                score=0.90,
                metadata={"anima": "test-anima", "origin": "human"},
            ),
        ]
        engine._retriever = self._make_retriever(results)
        engine._retriever_initialized = True

        medium, untrusted = await engine._channel_c_related_knowledge(["test"])
        assert "Human-provided knowledge" in medium
        assert untrusted == ""

    @pytest.mark.asyncio
    async def test_no_results_returns_empty_tuple(self, engine: PrimingEngine) -> None:
        """No search results → empty tuple."""
        engine._retriever = self._make_retriever([])
        engine._retriever_initialized = True

        medium, untrusted = await engine._channel_c_related_knowledge(["test"])
        assert medium == ""
        assert untrusted == ""

    @pytest.mark.asyncio
    async def test_no_keywords_returns_empty_tuple(self, engine: PrimingEngine) -> None:
        medium, untrusted = await engine._channel_c_related_knowledge([])
        assert medium == ""
        assert untrusted == ""

    @pytest.mark.asyncio
    async def test_shared_label_preserved(self, engine: PrimingEngine) -> None:
        """Shared chunks retain [shared] label in output."""
        results = [
            FakeSearchResult(
                content="Shared common knowledge",
                score=0.90,
                metadata={"anima": "shared", "origin": "system"},
            ),
        ]
        engine._retriever = self._make_retriever(results)
        engine._retriever_initialized = True

        medium, untrusted = await engine._channel_c_related_knowledge(["test"])
        assert "[shared]" in medium


# ── format_priming_section trust-separated output ─────────────


class TestFormatPrimingSectionTrustSeparation:
    """format_priming_section outputs trust-separated knowledge blocks."""

    def test_only_medium_knowledge(self) -> None:
        """Only medium knowledge → single block with trust=medium."""
        r = PrimingResult(related_knowledge="Some knowledge content")
        output = format_priming_section(r)
        assert 'trust="medium"' in output
        assert "related_knowledge_external" not in output

    def test_only_untrusted_knowledge(self) -> None:
        """Only untrusted → single block with trust=untrusted."""
        r = PrimingResult(related_knowledge_untrusted="External data")
        output = format_priming_section(r)
        assert 'trust="untrusted"' in output
        assert 'source="related_knowledge_external"' in output

    def test_both_medium_and_untrusted(self) -> None:
        """Both medium and untrusted → two separate blocks."""
        r = PrimingResult(
            related_knowledge="Trusted content",
            related_knowledge_untrusted="Untrusted content",
        )
        output = format_priming_section(r)
        assert 'source="related_knowledge"' in output
        assert 'trust="medium"' in output
        assert 'source="related_knowledge_external"' in output
        assert 'trust="untrusted"' in output
        assert output.index("related_knowledge") < output.index("related_knowledge_external")

    def test_medium_block_has_origin_when_untrusted_present(self) -> None:
        """When untrusted exists, medium block has origin=consolidation."""
        r = PrimingResult(
            related_knowledge="Trusted",
            related_knowledge_untrusted="Untrusted",
        )
        output = format_priming_section(r)
        assert 'origin="consolidation"' in output
        assert 'origin="external_platform"' in output

    def test_medium_block_no_origin_when_untrusted_absent(self) -> None:
        """When no untrusted, medium block does not include origin attribute."""
        r = PrimingResult(related_knowledge="Only medium")
        output = format_priming_section(r)
        assert 'origin="consolidation"' not in output

    def test_no_knowledge_at_all(self) -> None:
        """Neither medium nor untrusted → no knowledge section."""
        r = PrimingResult(sender_profile="profile")
        output = format_priming_section(r)
        assert "related_knowledge" not in output

    def test_empty_result(self) -> None:
        r = PrimingResult()
        output = format_priming_section(r)
        assert output == ""


# ── Consolidation origin propagation ──────────────────────────


class TestConsolidationOrigin:
    """ConsolidationEngine passes origin=consolidation to RAG index."""

    @pytest.fixture
    def engine(self, tmp_path: Path):
        from core.memory.consolidation import ConsolidationEngine

        anima_dir = tmp_path / "animas" / "test-anima"
        (anima_dir / "episodes").mkdir(parents=True)
        (anima_dir / "knowledge").mkdir(parents=True)
        return ConsolidationEngine(anima_dir, "test-anima")

    def test_update_rag_index_default_origin(self, engine, tmp_path: Path) -> None:
        """_update_rag_index defaults to origin='consolidation'."""
        test_file = engine.knowledge_dir / "test.md"
        test_file.write_text("# Test\n\nContent.", encoding="utf-8")

        mock_indexer = MagicMock()
        with (
            patch("core.memory.rag.MemoryIndexer", return_value=mock_indexer),
            patch("core.memory.rag.singleton.get_vector_store"),
        ):
            engine._update_rag_index(["test.md"])

        mock_indexer.index_file.assert_called_once()
        call_kwargs = mock_indexer.index_file.call_args
        assert call_kwargs[1]["origin"] == "consolidation"

    def test_rebuild_rag_index_knowledge_has_consolidation_origin(
        self, engine, tmp_path: Path,
    ) -> None:
        """_rebuild_rag_index passes origin='consolidation' for knowledge files."""
        test_file = engine.knowledge_dir / "test.md"
        test_file.write_text("# Test\n\nContent.", encoding="utf-8")

        mock_indexer = MagicMock()
        with (
            patch("core.memory.rag.MemoryIndexer", return_value=mock_indexer),
            patch("core.memory.rag.singleton.get_vector_store"),
        ):
            engine._rebuild_rag_index()

        # Find the knowledge index_file call
        knowledge_calls = [
            c for c in mock_indexer.index_file.call_args_list
            if c[1].get("memory_type") == "knowledge" or (len(c[0]) > 1 and c[0][1] == "knowledge")
        ]
        assert len(knowledge_calls) >= 1
        for call in knowledge_calls:
            assert call[1].get("origin") == "consolidation"


# ── resolve_trust integration with origin values ──────────────


class TestResolveTrustOrigins:
    """Verify resolve_trust() returns expected trust for all origin categories."""

    @pytest.mark.parametrize(
        "origin,expected_trust",
        [
            (ORIGIN_SYSTEM, "trusted"),
            (ORIGIN_HUMAN, "medium"),
            (ORIGIN_ANIMA, "trusted"),
            (ORIGIN_EXTERNAL_PLATFORM, "untrusted"),
            (ORIGIN_EXTERNAL_WEB, "untrusted"),
            (ORIGIN_CONSOLIDATION, "medium"),
            (ORIGIN_UNKNOWN, "untrusted"),
            ("", "untrusted"),
            (None, "untrusted"),
        ],
    )
    def test_origin_trust_mapping(self, origin: str | None, expected_trust: str) -> None:
        assert resolve_trust(origin) == expected_trust

    def test_unknown_origin_string_is_untrusted(self) -> None:
        assert resolve_trust("some_future_origin") == "untrusted"


# ── Inbox episode origin propagation ──────────────────────────


class TestInboxEpisodeOrigin:
    """_anima_inbox passes origin to append_episode."""

    def test_source_to_origin_mapping_exists(self) -> None:
        from core._anima_inbox import _SOURCE_TO_ORIGIN
        assert _SOURCE_TO_ORIGIN["slack"] == ORIGIN_EXTERNAL_PLATFORM
        assert _SOURCE_TO_ORIGIN["chatwork"] == ORIGIN_EXTERNAL_PLATFORM
        assert _SOURCE_TO_ORIGIN["human"] == ORIGIN_HUMAN
        assert _SOURCE_TO_ORIGIN["anima"] == ORIGIN_ANIMA
