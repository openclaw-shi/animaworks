from __future__ import annotations
# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from core.paths import get_common_knowledge_dir, get_common_skills_dir, get_company_dir, get_shared_dir
from core.schemas import ModelConfig

logger = logging.getLogger("animaworks.memory")


class MemoryManager:
    """File-system based library memory.

    The LLM searches memory autonomously via Grep/Read tools.
    This class handles the Python-side read/write operations.
    """

    def __init__(self, anima_dir: Path, base_dir: Path | None = None) -> None:
        self.anima_dir = anima_dir
        self.company_dir = get_company_dir()
        self.common_skills_dir = get_common_skills_dir()
        self.common_knowledge_dir = get_common_knowledge_dir()
        self.episodes_dir = anima_dir / "episodes"
        self.knowledge_dir = anima_dir / "knowledge"
        self.procedures_dir = anima_dir / "procedures"
        self.skills_dir = anima_dir / "skills"
        self.state_dir = anima_dir / "state"
        for d in (
            self.episodes_dir,
            self.knowledge_dir,
            self.procedures_dir,
            self.skills_dir,
            self.state_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        # RAG indexer is initialized lazily on first access to avoid
        # heavy model loading (sentence-transformers / CUDA) during
        # DigitalAnima construction.  See: _get_indexer()
        self._indexer = None
        self._indexer_initialized = False

    # ── RAG indexer initialization ────────────────────────

    def _init_indexer(self) -> None:
        """Initialize RAG indexer if dependencies are available.

        Called lazily by ``_get_indexer()`` on first access.
        Uses process-level singletons for ChromaVectorStore and embedding
        model to avoid costly repeated initialization.

        Also ensures the ``shared_common_knowledge`` collection is indexed
        from ``~/.animaworks/common_knowledge/``.  The hash-based dedup in
        :meth:`MemoryIndexer.index_file` makes repeated calls a no-op.
        """
        self._indexer_initialized = True
        try:
            from core.memory.rag import MemoryIndexer
            from core.memory.rag.singleton import get_vector_store

            vector_store = get_vector_store()
            anima_name = self.anima_dir.name
            self._indexer = MemoryIndexer(vector_store, anima_name, self.anima_dir)
            logger.debug("RAG indexer initialized for anima=%s", anima_name)

            # Ensure shared_common_knowledge collection exists
            self._ensure_shared_knowledge_indexed(vector_store)
        except ImportError:
            logger.debug("RAG dependencies not installed, indexing disabled")
        except Exception as e:
            logger.warning("Failed to initialize RAG indexer: %s", e)

    def _ensure_shared_knowledge_indexed(self, vector_store) -> None:
        """Index common_knowledge/ into ``shared_common_knowledge`` collection.

        Uses the existing hash-based dedup so repeated calls (once per
        anima process) are effectively no-ops after the first indexing.
        """
        ck_dir = self.common_knowledge_dir
        if not ck_dir.is_dir() or not any(ck_dir.rglob("*.md")):
            logger.debug("No common_knowledge files found, skipping shared indexing")
            return

        try:
            from core.memory.rag import MemoryIndexer
            from core.paths import get_data_dir

            data_dir = get_data_dir()
            shared_indexer = MemoryIndexer(
                vector_store,
                anima_name="shared",
                anima_dir=data_dir,
                collection_prefix="shared",
                embedding_model=self._indexer.embedding_model if self._indexer else None,
            )
            indexed = shared_indexer.index_directory(ck_dir, "common_knowledge")
            if indexed > 0:
                logger.info(
                    "Indexed %d chunks into shared_common_knowledge", indexed,
                )
        except Exception as e:
            logger.warning("Failed to index shared common_knowledge: %s", e)

    def _get_indexer(self):
        """Return the RAG indexer, initializing it on first call."""
        if not self._indexer_initialized:
            self._init_indexer()
        return self._indexer

    # ── Read ──────────────────────────────────────────────

    def _read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def read_company_vision(self) -> str:
        return self._read(self.company_dir / "vision.md")

    def read_identity(self) -> str:
        return self._read(self.anima_dir / "identity.md")

    def read_injection(self) -> str:
        return self._read(self.anima_dir / "injection.md")

    def read_specialty_prompt(self) -> str:
        """Read the role-specific specialty prompt."""
        return self._read(self.anima_dir / "specialty_prompt.md")

    def read_permissions(self) -> str:
        return self._read(self.anima_dir / "permissions.md")

    def read_current_state(self) -> str:
        return self._read(self.state_dir / "current_task.md") or "status: idle"

    def read_pending(self) -> str:
        return self._read(self.state_dir / "pending.md")

    def read_heartbeat_config(self) -> str:
        return self._read(self.anima_dir / "heartbeat.md")

    def read_cron_config(self) -> str:
        return self._read(self.anima_dir / "cron.md")

    def read_model_config(self) -> ModelConfig:
        """Load model config from unified config.json, with config.md fallback."""
        from core.config import (
            get_config_path,
            load_config,
            resolve_execution_mode,
            resolve_anima_config,
        )

        config_path = get_config_path()
        if config_path.exists():
            config = load_config(config_path)
            anima_name = self.anima_dir.name
            resolved, credential = resolve_anima_config(config, anima_name, anima_dir=self.anima_dir)
            # Derive env var name from credential name (e.g. "anthropic" -> "ANTHROPIC_API_KEY")
            cred_name = resolved.credential
            api_key_env = f"{cred_name.upper()}_API_KEY"
            mode = resolve_execution_mode(
                config, resolved.model, resolved.execution_mode,
            )
            return ModelConfig(
                model=resolved.model,
                fallback_model=resolved.fallback_model,
                max_tokens=resolved.max_tokens,
                max_turns=resolved.max_turns,
                api_key=credential.api_key or None,
                api_key_env=api_key_env,
                api_base_url=credential.base_url,
                context_threshold=resolved.context_threshold,
                max_chains=resolved.max_chains,
                conversation_history_threshold=resolved.conversation_history_threshold,
                execution_mode=resolved.execution_mode,
                supervisor=resolved.supervisor,
                speciality=resolved.speciality,
                resolved_mode=mode,
            )

        # Legacy fallback: parse config.md
        return self._read_model_config_from_md()

    def _read_model_config_from_md(self) -> ModelConfig:
        """Legacy parser for config.md (fallback when config.json absent)."""
        raw = self._read(self.anima_dir / "config.md")
        if not raw:
            return ModelConfig()

        # Ignore 備考/設定例 sections to avoid matching example lines
        for marker in ("## 備考", "### 設定例"):
            idx = raw.find(marker)
            if idx != -1:
                raw = raw[:idx]

        def _extract(key: str, default: str) -> str:
            m = re.search(rf"^-\s*{key}\s*:\s*(.+)$", raw, re.MULTILINE)
            return m.group(1).strip() if m else default

        defaults = ModelConfig()
        base_url = _extract("api_base_url", "")
        return ModelConfig(
            model=_extract("model", defaults.model),
            fallback_model=_extract("fallback_model", "") or defaults.fallback_model,
            max_tokens=int(_extract("max_tokens", str(defaults.max_tokens))),
            max_turns=int(_extract("max_turns", str(defaults.max_turns))),
            api_key_env=_extract("api_key_env", defaults.api_key_env),
            api_base_url=base_url or defaults.api_base_url,
        )

    def resolve_api_key(self, config: ModelConfig | None = None) -> str | None:
        """Resolve the actual API key (config.json direct value, then env var fallback)."""
        cfg = config or self.read_model_config()
        if cfg.api_key:
            return cfg.api_key
        return os.environ.get(cfg.api_key_env)

    def read_bootstrap(self) -> str:
        return self._read(self.anima_dir / "bootstrap.md")

    def read_today_episodes(self) -> str:
        path = self.episodes_dir / f"{date.today().isoformat()}.md"
        return self._read(path)

    def read_file(self, relpath: str) -> str:
        """Read an arbitrary file relative to anima_dir."""
        return self._read(self.anima_dir / relpath)

    def list_knowledge_files(self) -> list[str]:
        return [f.stem for f in sorted(self.knowledge_dir.glob("*.md"))]

    def list_episode_files(self) -> list[str]:
        return [
            f.stem for f in sorted(self.episodes_dir.glob("*.md"), reverse=True)
        ]

    def list_procedure_files(self) -> list[str]:
        return [f.stem for f in sorted(self.procedures_dir.glob("*.md"))]

    def list_skill_files(self) -> list[str]:
        return [f.stem for f in sorted(self.skills_dir.glob("*.md"))]

    @staticmethod
    def _extract_skill_summary(path: Path) -> str:
        """Extract the first line of the 概要 section from a skill file."""
        text = path.read_text(encoding="utf-8")
        in_overview = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "## 概要":
                in_overview = True
                continue
            if in_overview:
                if stripped.startswith("#"):
                    break
                if stripped:
                    return stripped
        return ""

    def list_skill_summaries(self) -> list[tuple[str, str]]:
        """Return (filename_stem, first_line_of_概要) for each personal skill."""
        return [
            (f.stem, self._extract_skill_summary(f))
            for f in sorted(self.skills_dir.glob("*.md"))
        ]

    def list_common_skill_summaries(self) -> list[tuple[str, str]]:
        """Return (filename_stem, first_line_of_概要) for each common skill."""
        if not self.common_skills_dir.is_dir():
            return []
        return [
            (f.stem, self._extract_skill_summary(f))
            for f in sorted(self.common_skills_dir.glob("*.md"))
        ]

    # ── Cron log ──────────────────────────────────────────

    _CRON_LOG_DIR = "state/cron_logs"
    _CRON_LOG_MAX_LINES = 50

    def append_cron_log(
        self, task_name: str, *, summary: str, duration_ms: int,
    ) -> None:
        """Append a cron execution result to the daily log."""
        log_dir = self.anima_dir / self._CRON_LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"{date.today().isoformat()}.jsonl"

        import json as _json
        entry = _json.dumps({
            "timestamp": datetime.now().isoformat(),
            "task": task_name,
            "summary": summary[:500],
            "duration_ms": duration_ms,
        }, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")

        # Keep file bounded
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) > self._CRON_LOG_MAX_LINES:
            path.write_text(
                "\n".join(lines[-self._CRON_LOG_MAX_LINES:]) + "\n",
                encoding="utf-8",
            )

    def append_cron_command_log(
        self,
        task_name: str,
        *,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_ms: int,
    ) -> None:
        """Append a command-type cron execution result to the daily log.

        Logs include exit code, line counts, and previews (first+last 5 lines).
        """
        log_dir = self.anima_dir / self._CRON_LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"{date.today().isoformat()}.jsonl"

        # Count lines
        stdout_lines_list = stdout.splitlines()
        stderr_lines_list = stderr.splitlines()
        stdout_line_count = len(stdout_lines_list)
        stderr_line_count = len(stderr_lines_list)

        # Generate preview: first 5 + last 5 lines, max 1000 chars total
        def make_preview(lines_list: list[str]) -> str:
            if not lines_list:
                return ""
            if len(lines_list) <= 10:
                preview = "\n".join(lines_list)
            else:
                preview = "\n".join(lines_list[:5] + ["..."] + lines_list[-5:])
            return preview[:1000]

        stdout_preview = make_preview(stdout_lines_list)
        stderr_preview = make_preview(stderr_lines_list)

        import json as _json
        entry = _json.dumps(
            {
                "timestamp": datetime.now().isoformat(),
                "task": task_name,
                "exit_code": exit_code,
                "stdout_lines": stdout_line_count,
                "stderr_lines": stderr_line_count,
                "stdout_preview": stdout_preview,
                "stderr_preview": stderr_preview,
                "duration_ms": duration_ms,
            },
            ensure_ascii=False,
        )
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")

        # Keep file bounded
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) > self._CRON_LOG_MAX_LINES:
            path.write_text(
                "\n".join(lines[-self._CRON_LOG_MAX_LINES:]) + "\n",
                encoding="utf-8",
            )

    def read_cron_log(self, days: int = 1) -> str:
        """Read cron logs for the last *days* days."""
        log_dir = self.anima_dir / self._CRON_LOG_DIR
        if not log_dir.is_dir():
            return ""

        import json as _json
        parts: list[str] = []
        for i in range(days):
            target = date.today() - timedelta(days=i)
            path = log_dir / f"{target.isoformat()}.jsonl"
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").strip().splitlines():
                try:
                    e = _json.loads(line)
                    parts.append(
                        f"- {e['timestamp']}: [{e['task']}] {e['summary'][:200]} "
                        f"({e['duration_ms']}ms)"
                    )
                except (_json.JSONDecodeError, KeyError):
                    continue
        return "\n".join(parts)

    # ── Shared user memory ────────────────────────────────

    @staticmethod
    def _shared_users_dir() -> Path:
        return get_shared_dir() / "users"

    def list_shared_users(self) -> list[str]:
        """List user subdirectories under shared/users/."""
        d = self._shared_users_dir()
        if not d.is_dir():
            return []
        return [p.name for p in sorted(d.iterdir()) if p.is_dir()]

    # ── Write ─────────────────────────────────────────────

    def append_episode(self, entry: str) -> None:
        path = self.episodes_dir / f"{date.today().isoformat()}.md"
        if not path.exists():
            path.write_text(
                f"# {date.today().isoformat()} 行動ログ\n\n", encoding="utf-8"
            )
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n{entry}\n")
        logger.debug("Episode appended, length=%d", len(entry))

        # Index the updated episode file (incremental)
        if self._get_indexer():
            try:
                self._get_indexer().index_file(path, "episodes")
            except Exception as e:
                logger.warning("Failed to index episode file: %s", e)

    def update_state(self, content: str) -> None:
        (self.state_dir / "current_task.md").write_text(content, encoding="utf-8")

    def update_pending(self, content: str) -> None:
        (self.state_dir / "pending.md").write_text(content, encoding="utf-8")

    def write_knowledge(self, topic: str, content: str) -> None:
        safe = re.sub(r"[^\w\-_]", "_", topic)
        path = self.knowledge_dir / f"{safe}.md"
        path.write_text(content, encoding="utf-8")
        logger.debug("Knowledge written topic='%s' length=%d", topic, len(content))

        # Index the new/updated knowledge file
        if self._get_indexer():
            try:
                self._get_indexer().index_file(path, "knowledge")
            except Exception as e:
                logger.warning("Failed to index knowledge file: %s", e)

    # ── Read helpers for Mode B (assisted) ──────────────────

    def read_recent_episodes(self, days: int = 7) -> str:
        """Return concatenated episode logs for the last *days* days."""
        parts: list[str] = []
        today = date.today()
        for offset in range(days):
            d = today - timedelta(days=offset)
            path = self.episodes_dir / f"{d.isoformat()}.md"
            if path.exists():
                parts.append(path.read_text(encoding="utf-8"))
        return "\n\n".join(parts)

    def search_memory_text(
        self, query: str, scope: str = "all"
    ) -> list[tuple[str, str]]:
        """Search memory files by keyword and optional vector similarity.

        Returns ``(filename, matching_line)`` pairs.

        *scope* can be ``"knowledge"``, ``"episodes"``, ``"procedures"``,
        ``"common_knowledge"``, or ``"all"`` (default).

        When RAG dependencies are available the method performs **hybrid
        search**: keyword matches are returned first, followed by
        vector-similarity results that were not already found by keyword.
        """
        dirs: list[Path] = []
        if scope in ("knowledge", "all"):
            dirs.append(self.knowledge_dir)
        if scope in ("episodes", "all"):
            dirs.append(self.episodes_dir)
        if scope in ("procedures", "all"):
            dirs.append(self.procedures_dir)
        if scope in ("common_knowledge", "all"):
            if self.common_knowledge_dir.is_dir():
                dirs.append(self.common_knowledge_dir)

        # Keyword search
        results: list[tuple[str, str]] = []
        q = query.lower()
        for d in dirs:
            for f in d.glob("*.md"):
                for line in f.read_text(encoding="utf-8").splitlines():
                    if q in line.lower():
                        results.append((f.name, line.strip()))

        # Hybrid: append vector search results when RAG is available
        if self._indexer is not None and scope in ("knowledge", "common_knowledge", "all"):
            try:
                vector_hits = self._vector_search_memory(query, scope)
                seen_files = {r[0] for r in results}
                for fname, snippet in vector_hits:
                    if fname not in seen_files:
                        results.append((fname, snippet))
                        seen_files.add(fname)
            except Exception as e:
                logger.debug("Vector search augmentation failed: %s", e)

        return results

    def _vector_search_memory(
        self, query: str, scope: str,
    ) -> list[tuple[str, str]]:
        """Perform vector search to augment keyword results.

        Returns ``(filename, first_line_of_content)`` pairs.
        """
        from core.memory.rag.retriever import MemoryRetriever

        anima_name = self.anima_dir.name
        retriever = MemoryRetriever(
            self._indexer.vector_store,
            self._indexer,
            self.knowledge_dir,
        )

        include_shared = scope in ("common_knowledge", "all")
        rag_results = retriever.search(
            query=query,
            anima_name=anima_name,
            memory_type="knowledge",
            top_k=5,
            include_shared=include_shared,
        )

        # Record access (Hebbian LTP: strengthen frequently accessed memories)
        if rag_results:
            retriever.record_access(rag_results, anima_name)

        hits: list[tuple[str, str]] = []
        for r in rag_results:
            source = r.metadata.get("source_file", r.doc_id)
            first_line = r.content.split("\n", 1)[0].strip()
            hits.append((str(source), first_line))
        return hits

    def search_procedures(self, query: str) -> list[tuple[str, str]]:
        """Search procedures/ by keyword."""
        return self.search_memory_text(query, scope="procedures")

    # ── Search (Python-side; LLM uses Grep directly) ─────

    def search_knowledge(self, query: str) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        q = query.lower()
        for f in self.knowledge_dir.glob("*.md"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if q in line.lower():
                    results.append((f.name, line.strip()))
        logger.debug("search_knowledge query='%s' results=%d", query, len(results))
        return results