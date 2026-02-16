"""Unit tests for common_knowledge RAG infrastructure.

Tests the cross-cutting changes that enable shared common_knowledge:
- MemoryIndexer with collection_prefix
- FileWatcher with extra_watch_dirs
- MemoryRetriever with include_shared
- ToolHandler read_memory_file with common_knowledge/ prefix
- _ensure_runtime_only_dirs creates common_knowledge directory
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── MemoryIndexer collection_prefix ──────────────────────────


class TestMemoryIndexerCollectionPrefix:
    """Test that MemoryIndexer uses collection_prefix for naming."""

    @pytest.fixture
    def person_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "test_person"
        d.mkdir()
        (d / "knowledge").mkdir()
        return d

    def _make_indexer(self, vector_store, person_name, person_dir, **kwargs):
        """Create a MemoryIndexer with mocked embedding model."""
        from core.memory.rag.indexer import MemoryIndexer

        with patch.object(MemoryIndexer, "_init_embedding_model"):
            indexer = MemoryIndexer(
                vector_store,
                person_name=person_name,
                person_dir=person_dir,
                **kwargs,
            )
            return indexer

    @pytest.fixture
    def indexer_with_prefix(self, person_dir: Path):
        """Create a MemoryIndexer with collection_prefix='shared'."""
        return self._make_indexer(
            MagicMock(), "test_person", person_dir, collection_prefix="shared",
        )

    @pytest.fixture
    def indexer_default_prefix(self, person_dir: Path):
        """Create a MemoryIndexer without explicit collection_prefix."""
        return self._make_indexer(MagicMock(), "alice", person_dir)

    def test_collection_prefix_defaults_to_person_name(
        self, indexer_default_prefix,
    ):
        assert indexer_default_prefix.collection_prefix == "alice"

    def test_collection_prefix_override(self, indexer_with_prefix):
        assert indexer_with_prefix.collection_prefix == "shared"

    def test_make_chunk_id_uses_collection_prefix(
        self, indexer_with_prefix, person_dir: Path,
    ):
        test_file = person_dir / "knowledge" / "test.md"
        test_file.write_text("content", encoding="utf-8")
        chunk_id = indexer_with_prefix._make_chunk_id(test_file, "knowledge", 0)
        assert chunk_id.startswith("shared/")
        assert "knowledge" in chunk_id
        assert "test.md" in chunk_id

    def test_make_chunk_id_no_path_duplication(
        self, indexer_with_prefix, person_dir: Path,
    ):
        """Chunk ID must NOT contain doubled directory (e.g. knowledge/knowledge/)."""
        test_file = person_dir / "knowledge" / "test.md"
        test_file.write_text("content", encoding="utf-8")
        chunk_id = indexer_with_prefix._make_chunk_id(test_file, "knowledge", 0)
        # Expected: shared/knowledge/test.md#0
        assert chunk_id == "shared/knowledge/test.md#0"
        # Must not have doubled path
        assert "knowledge/knowledge/" not in chunk_id

    def test_make_chunk_id_no_path_duplication_episodes(
        self, indexer_default_prefix, person_dir: Path,
    ):
        """Episode chunk IDs must not double the 'episodes' directory."""
        episodes_dir = person_dir / "episodes"
        episodes_dir.mkdir(exist_ok=True)
        test_file = episodes_dir / "2026-02-16.md"
        test_file.write_text("content", encoding="utf-8")
        chunk_id = indexer_default_prefix._make_chunk_id(test_file, "episodes", 0)
        assert chunk_id == "alice/episodes/2026-02-16.md#0"
        assert "episodes/episodes/" not in chunk_id

    def test_make_chunk_id_common_knowledge(
        self, indexer_with_prefix, person_dir: Path,
    ):
        """common_knowledge type should produce clean IDs."""
        ck_dir = person_dir / "common_knowledge"
        ck_dir.mkdir(exist_ok=True)
        test_file = ck_dir / "guide.md"
        test_file.write_text("content", encoding="utf-8")
        chunk_id = indexer_with_prefix._make_chunk_id(test_file, "common_knowledge", 0)
        assert chunk_id == "shared/common_knowledge/guide.md#0"
        assert "common_knowledge/common_knowledge/" not in chunk_id

    def test_make_chunk_id_default_uses_person_name(
        self, indexer_default_prefix, person_dir: Path,
    ):
        test_file = person_dir / "knowledge" / "test.md"
        test_file.write_text("content", encoding="utf-8")
        chunk_id = indexer_default_prefix._make_chunk_id(test_file, "knowledge", 0)
        assert chunk_id.startswith("alice/")

    def test_extract_metadata_uses_collection_prefix(
        self, indexer_with_prefix, person_dir: Path,
    ):
        test_file = person_dir / "knowledge" / "test.md"
        test_file.write_text("Some content here", encoding="utf-8")
        metadata = indexer_with_prefix._extract_metadata(
            test_file, "Some content here", "knowledge", 0, 1,
        )
        assert metadata["person"] == "shared"

    def test_extract_metadata_default_uses_person_name(
        self, indexer_default_prefix, person_dir: Path,
    ):
        test_file = person_dir / "knowledge" / "test.md"
        test_file.write_text("Some content here", encoding="utf-8")
        metadata = indexer_default_prefix._extract_metadata(
            test_file, "Some content here", "knowledge", 0, 1,
        )
        assert metadata["person"] == "alice"

    def test_index_file_uses_collection_prefix_for_collection_name(
        self, person_dir: Path,
    ):
        """index_file() creates collection named '{prefix}_{memory_type}'."""
        vector_store = MagicMock()
        indexer = self._make_indexer(
            vector_store, "test_person", person_dir, collection_prefix="shared",
        )
        # Mock embedding generation
        indexer._generate_embeddings = MagicMock(
            return_value=[[0.0] * 384],
        )

        test_file = person_dir / "knowledge" / "doc.md"
        test_file.write_text(
            "# Title\n\n## Section One\n\nContent here for testing.",
            encoding="utf-8",
        )

        indexer.index_file(test_file, "common_knowledge", force=True)

        # Verify create_collection was called with shared prefix
        vector_store.create_collection.assert_called_with(
            "shared_common_knowledge", 384,
        )


# ── FileWatcher extra_watch_dirs ─────────────────────────────


class TestFileWatcherExtraWatchDirs:
    """Test FileWatcher with extra_watch_dirs for common_knowledge."""

    @pytest.fixture
    def person_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "person"
        d.mkdir()
        for sub in ("knowledge", "episodes", "procedures", "skills"):
            (d / sub).mkdir()
        return d

    @pytest.fixture
    def common_knowledge_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "common_knowledge"
        d.mkdir()
        return d

    def test_get_memory_type_recognizes_extra_watch_dir(
        self, person_dir: Path, common_knowledge_dir: Path,
    ):
        from core.memory.rag.watcher import FileWatcher

        indexer = MagicMock()
        watcher = FileWatcher(
            person_dir,
            indexer,
            extra_watch_dirs=[(common_knowledge_dir, "common_knowledge")],
        )

        test_file = common_knowledge_dir / "shared_doc.md"
        memory_type = watcher._get_memory_type(test_file)
        assert memory_type == "common_knowledge"

    def test_get_memory_type_still_recognizes_personal_dirs(
        self, person_dir: Path, common_knowledge_dir: Path,
    ):
        from core.memory.rag.watcher import FileWatcher

        indexer = MagicMock()
        watcher = FileWatcher(
            person_dir,
            indexer,
            extra_watch_dirs=[(common_knowledge_dir, "common_knowledge")],
        )

        assert watcher._get_memory_type(person_dir / "knowledge" / "k.md") == "knowledge"
        assert watcher._get_memory_type(person_dir / "episodes" / "e.md") == "episodes"
        assert watcher._get_memory_type(person_dir / "procedures" / "p.md") == "procedures"
        assert watcher._get_memory_type(person_dir / "skills" / "s.md") == "skills"

    def test_get_memory_type_extra_dir_takes_priority(
        self, tmp_path: Path,
    ):
        """If a file could match both extra and personal, extra wins (checked first)."""
        from core.memory.rag.watcher import FileWatcher

        # Create a scenario where extra_dir is a subdir of person_dir
        person_dir = tmp_path / "person"
        person_dir.mkdir()
        knowledge_dir = person_dir / "knowledge"
        knowledge_dir.mkdir()

        indexer = MagicMock()
        watcher = FileWatcher(
            person_dir,
            indexer,
            extra_watch_dirs=[(knowledge_dir, "overridden_type")],
        )

        result = watcher._get_memory_type(knowledge_dir / "test.md")
        assert result == "overridden_type"

    def test_get_memory_type_unrecognized_returns_none(
        self, person_dir: Path, common_knowledge_dir: Path,
    ):
        from core.memory.rag.watcher import FileWatcher

        indexer = MagicMock()
        watcher = FileWatcher(
            person_dir,
            indexer,
            extra_watch_dirs=[(common_knowledge_dir, "common_knowledge")],
        )

        result = watcher._get_memory_type(Path("/some/random/path.md"))
        assert result is None

    def test_extra_watch_dirs_default_empty(self, person_dir: Path):
        from core.memory.rag.watcher import FileWatcher

        indexer = MagicMock()
        watcher = FileWatcher(person_dir, indexer)
        assert watcher._extra_watch_dirs == []

    def test_start_schedules_extra_watch_dirs(
        self, person_dir: Path, common_knowledge_dir: Path,
    ):
        """start() should schedule the extra_watch_dirs for observation."""
        from core.memory.rag.watcher import FileWatcher

        indexer = MagicMock()
        watcher = FileWatcher(
            person_dir,
            indexer,
            extra_watch_dirs=[(common_knowledge_dir, "common_knowledge")],
        )

        with patch("core.memory.rag.watcher.Observer") as MockObserver:
            mock_observer = MagicMock()
            MockObserver.return_value = mock_observer

            watcher.start()

            # Collect all scheduled directories
            scheduled_dirs = [
                call[0][1]  # second arg is the path string
                for call in mock_observer.schedule.call_args_list
            ]
            assert str(common_knowledge_dir) in scheduled_dirs

            watcher.stop()


# ── MemoryRetriever include_shared ───────────────────────────


class TestMemoryRetrieverIncludeShared:
    """Test MemoryRetriever search with include_shared flag."""

    @pytest.fixture
    def mock_vector_store(self):
        return MagicMock()

    @pytest.fixture
    def mock_indexer(self):
        indexer = MagicMock()
        indexer._generate_embeddings.return_value = [[0.1, 0.2, 0.3]]
        return indexer

    @pytest.fixture
    def retriever(self, mock_vector_store, mock_indexer, tmp_path: Path):
        from core.memory.rag.retriever import MemoryRetriever

        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()
        return MemoryRetriever(mock_vector_store, mock_indexer, knowledge_dir)

    def test_search_without_shared(
        self, retriever, mock_vector_store,
    ):
        """Without include_shared, only personal collection is searched."""
        mock_vector_store.query.return_value = []

        retriever.search(
            query="test",
            person_name="alice",
            memory_type="knowledge",
            top_k=3,
            include_shared=False,
        )

        # Should only query alice_knowledge, NOT shared_common_knowledge
        assert mock_vector_store.query.call_count == 1
        call_kwargs = mock_vector_store.query.call_args
        queried_collection = call_kwargs.kwargs.get("collection")
        assert queried_collection == "alice_knowledge"

    def test_search_with_shared_searches_both_collections(
        self, retriever, mock_vector_store,
    ):
        """With include_shared=True, both personal and shared collections are searched."""
        mock_vector_store.query.return_value = []

        retriever.search(
            query="test",
            person_name="alice",
            memory_type="knowledge",
            top_k=3,
            include_shared=True,
        )

        # Should query both alice_knowledge and shared_common_knowledge
        assert mock_vector_store.query.call_count == 2
        queried_collections = [
            call.kwargs.get("collection")
            for call in mock_vector_store.query.call_args_list
        ]
        assert "alice_knowledge" in queried_collections
        assert "shared_common_knowledge" in queried_collections

    def test_search_with_shared_non_knowledge_type_skips_shared(
        self, retriever, mock_vector_store,
    ):
        """include_shared only activates for memory_type='knowledge'."""
        mock_vector_store.query.return_value = []

        retriever.search(
            query="test",
            person_name="alice",
            memory_type="episodes",
            top_k=3,
            include_shared=True,
        )

        # Should only query alice_episodes, not shared_common_knowledge
        assert mock_vector_store.query.call_count == 1

    def test_search_with_shared_merges_results(
        self, retriever, mock_vector_store, mock_indexer,
    ):
        """Shared results are merged with personal results and sorted by score."""
        # Create mock query results
        personal_result = MagicMock()
        personal_result.document.id = "personal_doc"
        personal_result.document.content = "Personal knowledge"
        personal_result.score = 0.9
        personal_result.document.metadata = {
            "person": "alice",
            "updated_at": "2026-02-15T00:00:00",
        }

        shared_result = MagicMock()
        shared_result.document.id = "shared_doc"
        shared_result.document.content = "Shared knowledge"
        shared_result.score = 0.8
        shared_result.document.metadata = {
            "person": "shared",
            "updated_at": "2026-02-15T00:00:00",
        }

        mock_vector_store.query.side_effect = [
            [personal_result],   # alice_knowledge query
            [shared_result],     # shared_common_knowledge query
        ]

        results = retriever.search(
            query="test",
            person_name="alice",
            memory_type="knowledge",
            top_k=3,
            include_shared=True,
        )

        assert len(results) == 2
        # Both should be present
        doc_ids = {r.doc_id for r in results}
        assert "personal_doc" in doc_ids
        assert "shared_doc" in doc_ids


# ── _ensure_runtime_only_dirs ────────────────────────────────


class TestEnsureRuntimeOnlyDirs:
    """Test that _ensure_runtime_only_dirs creates common_knowledge."""

    def test_creates_common_knowledge_dir(self, tmp_path: Path):
        from core.init import _ensure_runtime_only_dirs

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        _ensure_runtime_only_dirs(data_dir)

        assert (data_dir / "common_knowledge").is_dir()

    def test_idempotent(self, tmp_path: Path):
        from core.init import _ensure_runtime_only_dirs

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        _ensure_runtime_only_dirs(data_dir)
        _ensure_runtime_only_dirs(data_dir)

        assert (data_dir / "common_knowledge").is_dir()

    def test_creates_all_expected_dirs(self, tmp_path: Path):
        from core.init import _ensure_runtime_only_dirs

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        _ensure_runtime_only_dirs(data_dir)

        assert (data_dir / "persons").is_dir()
        assert (data_dir / "shared" / "inbox").is_dir()
        assert (data_dir / "shared" / "users").is_dir()
        assert (data_dir / "tmp" / "attachments").is_dir()
        assert (data_dir / "common_skills").is_dir()
        assert (data_dir / "common_knowledge").is_dir()


# ── ToolHandler read_memory_file with common_knowledge/ ──────


class TestToolHandlerCommonKnowledgeRead:
    """Test ToolHandler._handle_read_memory_file with common_knowledge/ prefix."""

    @pytest.fixture
    def person_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "persons" / "test-person"
        d.mkdir(parents=True)
        return d

    @pytest.fixture
    def handler(self, person_dir: Path):
        from core.tooling.handler import ToolHandler

        memory = MagicMock()
        memory.read_permissions.return_value = ""
        memory.search_memory_text.return_value = []
        return ToolHandler(
            person_dir=person_dir,
            memory=memory,
            messenger=None,
            tool_registry=[],
        )

    def test_common_knowledge_prefix_resolves_to_shared_dir(
        self, handler, tmp_path: Path,
    ):
        ck_dir = tmp_path / "shared_ck"
        ck_dir.mkdir()
        (ck_dir / "info.md").write_text("shared info content", encoding="utf-8")

        with patch(
            "core.paths.get_common_knowledge_dir",
            return_value=ck_dir,
        ):
            result = handler.handle(
                "read_memory_file",
                {"path": "common_knowledge/info.md"},
            )
        assert result == "shared info content"

    def test_common_knowledge_prefix_nested_path(
        self, handler, tmp_path: Path,
    ):
        ck_dir = tmp_path / "shared_ck"
        sub = ck_dir / "subdir"
        sub.mkdir(parents=True)
        (sub / "deep.md").write_text("deep content", encoding="utf-8")

        with patch(
            "core.paths.get_common_knowledge_dir",
            return_value=ck_dir,
        ):
            result = handler.handle(
                "read_memory_file",
                {"path": "common_knowledge/subdir/deep.md"},
            )
        assert result == "deep content"

    def test_non_common_knowledge_prefix_uses_person_dir(
        self, handler, person_dir: Path,
    ):
        (person_dir / "knowledge").mkdir(exist_ok=True)
        (person_dir / "knowledge" / "local.md").write_text(
            "local content", encoding="utf-8",
        )
        result = handler.handle(
            "read_memory_file",
            {"path": "knowledge/local.md"},
        )
        assert result == "local content"


# ── MemoryManager._vector_search_memory ──────────────────────


class TestManagerVectorSearchMemory:
    """Test MemoryManager._vector_search_memory with include_shared."""

    @pytest.fixture
    def person_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "person"
        d.mkdir()
        return d

    def test_vector_search_sets_include_shared_for_common_knowledge(
        self, person_dir: Path, data_dir: Path,
    ):
        """scope='common_knowledge' passes include_shared=True to retriever."""
        from core.memory.manager import MemoryManager

        mm = MemoryManager(person_dir)

        # Mock the indexer so _vector_search_memory runs
        mm._indexer = MagicMock()
        mm._indexer.vector_store = MagicMock()

        with patch("core.memory.rag.retriever.MemoryRetriever") as MockRetriever:
            mock_retriever = MagicMock()
            mock_retriever.search.return_value = []
            MockRetriever.return_value = mock_retriever

            mm._vector_search_memory("test query", "common_knowledge")

            # Verify include_shared=True was passed
            mock_retriever.search.assert_called_once()
            call_kwargs = mock_retriever.search.call_args
            assert call_kwargs.kwargs.get("include_shared") is True

    def test_vector_search_sets_include_shared_for_all(
        self, person_dir: Path, data_dir: Path,
    ):
        """scope='all' passes include_shared=True to retriever."""
        from core.memory.manager import MemoryManager

        mm = MemoryManager(person_dir)
        mm._indexer = MagicMock()
        mm._indexer.vector_store = MagicMock()

        with patch("core.memory.rag.retriever.MemoryRetriever") as MockRetriever:
            mock_retriever = MagicMock()
            mock_retriever.search.return_value = []
            MockRetriever.return_value = mock_retriever

            mm._vector_search_memory("test query", "all")

            call_kwargs = mock_retriever.search.call_args
            assert call_kwargs.kwargs.get("include_shared") is True

    def test_vector_search_no_shared_for_knowledge_only(
        self, person_dir: Path, data_dir: Path,
    ):
        """scope='knowledge' does NOT pass include_shared=True."""
        from core.memory.manager import MemoryManager

        mm = MemoryManager(person_dir)
        mm._indexer = MagicMock()
        mm._indexer.vector_store = MagicMock()

        with patch("core.memory.rag.retriever.MemoryRetriever") as MockRetriever:
            mock_retriever = MagicMock()
            mock_retriever.search.return_value = []
            MockRetriever.return_value = mock_retriever

            mm._vector_search_memory("test query", "knowledge")

            call_kwargs = mock_retriever.search.call_args
            assert call_kwargs.kwargs.get("include_shared") is False
