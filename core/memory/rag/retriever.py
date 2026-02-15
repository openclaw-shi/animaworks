from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Dense vector retrieval system with temporal decay and spreading activation.

Implements:
- Dense vector similarity search (semantic)
- Temporal decay scoring (newer documents ranked higher)
- Spreading activation via knowledge graph (optional)
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("animaworks.rag.retriever")

# ── Configuration ───────────────────────────────────────────────────

WEIGHT_RECENCY = 0.2

# Temporal decay half-life (days)
RECENCY_HALF_LIFE_DAYS = 30.0


# ── Data structures ─────────────────────────────────────────────────


@dataclass
class RetrievalResult:
    """A retrieved document with combined score."""

    doc_id: str
    content: str
    score: float
    metadata: dict[str, str | int | float | list[str]]
    source_scores: dict[str, float]  # Debug info: individual scores


# ── MemoryRetriever ────────────────────────────────────────────────


class MemoryRetriever:
    """Dense vector search with temporal decay and spreading activation.

    Pipeline:
      Query → Dense Vector Search → Temporal Decay → Sort → Spreading Activation → Results
    """

    def __init__(
        self,
        vector_store,  # VectorStore instance
        indexer,  # MemoryIndexer instance
        knowledge_dir: Path,
    ) -> None:
        """Initialize memory retriever.

        Args:
            vector_store: VectorStore instance
            indexer: MemoryIndexer instance (for embedding generation)
            knowledge_dir: Path to knowledge directory (for spreading activation)
        """
        self.vector_store = vector_store
        self.indexer = indexer
        self.knowledge_dir = knowledge_dir
        self._knowledge_graph = None  # Lazy initialization

    # ── Main search API ─────────────────────────────────────────────

    def search(
        self,
        query: str,
        person_name: str,
        memory_type: str = "knowledge",
        top_k: int = 3,
        enable_spreading_activation: bool = False,
        *,
        include_shared: bool = False,
    ) -> list[RetrievalResult]:
        """Perform dense vector search with temporal decay.

        Args:
            query: Search query text
            person_name: Person name (for collection selection)
            memory_type: Memory type (knowledge, episodes, etc.)
            top_k: Number of results to return
            enable_spreading_activation: Enable graph-based spreading activation
            include_shared: Also search ``shared_common_knowledge`` collection
                and merge results by score.

        Returns:
            List of retrieval results sorted by combined score
        """
        logger.debug(
            "Vector search: query='%s', person=%s, type=%s, top_k=%d, "
            "spreading=%s, shared=%s",
            query,
            person_name,
            memory_type,
            top_k,
            enable_spreading_activation,
            include_shared,
        )

        # 1. Dense Vector search (personal collection)
        vector_results = self._vector_search(query, person_name, memory_type, top_k * 2)

        # 1b. Shared collection search (if requested)
        if include_shared and memory_type == "knowledge":
            shared_results = self._vector_search_collection(
                query, "shared_common_knowledge", top_k * 2,
            )
            vector_results.extend(shared_results)

        # 2. Convert to RetrievalResult
        results = [
            RetrievalResult(
                doc_id=doc_id,
                content=content,
                score=score,
                metadata=metadata,
                source_scores={"vector": score},
            )
            for doc_id, content, score, metadata in vector_results
        ]

        # 3. Apply temporal decay
        results = self._apply_temporal_decay(results)

        # 4. Sort & top_k
        results.sort(key=lambda r: r.score, reverse=True)
        initial_results = results[:top_k]

        # 5. Apply spreading activation if enabled
        if enable_spreading_activation and memory_type in ("knowledge", "episodes"):
            try:
                expanded = self._apply_spreading_activation(initial_results, person_name)
                return expanded
            except Exception as e:
                logger.warning("Spreading activation failed, returning initial results: %s", e)
                return initial_results

        return initial_results

    # ── Search methods ──────────────────────────────────────────────

    def _vector_search(
        self,
        query: str,
        person_name: str,
        memory_type: str,
        top_k: int,
    ) -> list[tuple[str, str, float, dict]]:
        """Perform vector similarity search on a person collection.

        Returns:
            List of (doc_id, content, score, metadata) tuples
        """
        collection_name = f"{person_name}_{memory_type}"
        return self._vector_search_collection(query, collection_name, top_k)

    def _vector_search_collection(
        self,
        query: str,
        collection_name: str,
        top_k: int,
    ) -> list[tuple[str, str, float, dict]]:
        """Perform vector similarity search on a named collection.

        Returns:
            List of (doc_id, content, score, metadata) tuples
        """
        # Generate query embedding
        embedding = self.indexer._generate_embeddings([query])[0]

        # Query vector store
        results = self.vector_store.query(
            collection=collection_name,
            embedding=embedding,
            top_k=top_k,
        )

        return [
            (r.document.id, r.document.content, r.score, r.document.metadata)
            for r in results
        ]

    # ── Score adjustment ────────────────────────────────────────────

    def _apply_temporal_decay(
        self,
        results: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        """Apply temporal decay to scores based on document age.

        Uses exponential decay: decay_factor = 0.5 ^ (age_days / half_life)
        """
        now = datetime.now()

        for result in results:
            # Extract update timestamp from metadata
            updated_at_str = result.metadata.get("updated_at")
            if not updated_at_str:
                # No timestamp - use neutral decay (0.5)
                decay_factor = 0.5
            else:
                try:
                    updated_at = datetime.fromisoformat(str(updated_at_str))
                    age_days = (now - updated_at).total_seconds() / 86400.0

                    # Exponential decay
                    decay_factor = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
                except (ValueError, TypeError):
                    decay_factor = 0.5

            # Apply decay with weight
            recency_score = WEIGHT_RECENCY * decay_factor
            result.score = result.score + recency_score
            result.source_scores["recency"] = recency_score

        return results

    # ── Spreading activation ────────────────────────────────────────

    def _apply_spreading_activation(
        self,
        initial_results: list[RetrievalResult],
        person_name: str,
    ) -> list[RetrievalResult]:
        """Apply spreading activation to expand search results.

        Tries loading cached graph first, then falls back to full build.

        Args:
            initial_results: Initial search results
            person_name: Person name

        Returns:
            Expanded results with activated neighbors
        """
        # Lazy initialization of knowledge graph
        if self._knowledge_graph is None:
            try:
                from core.memory.rag.graph import KnowledgeGraph

                self._knowledge_graph = KnowledgeGraph(
                    self.vector_store,
                    self.indexer,
                )

                # Try loading from cache first
                cache_dir = self.knowledge_dir.parent / "vectordb"
                if not self._knowledge_graph.load_graph(cache_dir):
                    # Cache miss: full build and save
                    self._knowledge_graph.build_graph(person_name, self.knowledge_dir)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    self._knowledge_graph.save_graph(cache_dir)

            except Exception as e:
                logger.warning("Failed to initialize knowledge graph: %s", e)
                return initial_results

        # Expand results using graph
        return self._knowledge_graph.expand_search_results(initial_results)
