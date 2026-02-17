"""Unit tests for skill metadata extraction and matching.

Covers:
- MemoryManager._extract_skill_meta()  (core/memory/manager.py)
- match_skills_by_description()        (core/memory/manager.py)
- _classify_message_for_skill_budget() (core/prompt/builder.py)
- _build_skill_body()                  (core/prompt/builder.py)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.schemas import SkillMeta
from core.memory.manager import MemoryManager, match_skills_by_description
from core.prompt.builder import _classify_message_for_skill_budget, _build_skill_body


# ── _extract_skill_meta ──────────────────────────────────


class TestExtractSkillMeta:
    """Tests for MemoryManager._extract_skill_meta()."""

    def test_parse_yaml_frontmatter(self, tmp_path: Path) -> None:
        """YAML frontmatter with name + description is correctly parsed."""
        skill_file = tmp_path / "deploy.md"
        skill_file.write_text(
            "---\n"
            "name: deploy-skill\n"
            "description: デプロイ手順「deploy」「リリース」\n"
            "---\n"
            "\n"
            "# Deploy Skill\n"
            "\nBody content here.\n",
            encoding="utf-8",
        )

        meta = MemoryManager._extract_skill_meta(skill_file)

        assert meta.name == "deploy-skill"
        assert meta.description == "デプロイ手順「deploy」「リリース」"
        assert meta.path == skill_file
        assert meta.is_common is False

    def test_no_frontmatter_uses_filename(self, tmp_path: Path) -> None:
        """File without frontmatter uses filename stem as name, empty description."""
        skill_file = tmp_path / "my-skill.md"
        skill_file.write_text(
            "# My Skill\n\nSome instructions.\n",
            encoding="utf-8",
        )

        meta = MemoryManager._extract_skill_meta(skill_file)

        assert meta.name == "my-skill"
        assert meta.description == ""
        assert meta.path == skill_file

    def test_legacy_format_overview_section(self, tmp_path: Path) -> None:
        """Legacy format with ## 概要 extracts first line as description."""
        skill_file = tmp_path / "legacy.md"
        skill_file.write_text(
            "# レガシースキル\n"
            "\n"
            "## 概要\n"
            "\n"
            "cronジョブの設定と管理を行うスキル\n"
            "\n"
            "## 手順\n"
            "\n"
            "1. 手順内容\n",
            encoding="utf-8",
        )

        meta = MemoryManager._extract_skill_meta(skill_file)

        assert meta.name == "legacy"
        assert meta.description == "cronジョブの設定と管理を行うスキル"

    def test_frontmatter_with_extra_fields(self, tmp_path: Path) -> None:
        """Extra fields (version, metadata) do not interfere with extraction."""
        skill_file = tmp_path / "advanced.md"
        skill_file.write_text(
            "---\n"
            "name: advanced-tool\n"
            "description: 高度な検索「search」「query」\n"
            "version: 2.1\n"
            "metadata:\n"
            "  author: test\n"
            "  tags: [search, query]\n"
            "---\n"
            "\n"
            "Body.\n",
            encoding="utf-8",
        )

        meta = MemoryManager._extract_skill_meta(skill_file)

        assert meta.name == "advanced-tool"
        assert meta.description == "高度な検索「search」「query」"

    def test_is_common_flag(self, tmp_path: Path) -> None:
        """is_common flag is correctly set when specified."""
        skill_file = tmp_path / "shared.md"
        skill_file.write_text(
            "---\n"
            "name: shared-skill\n"
            "description: 共有スキル\n"
            "---\n"
            "\nContent.\n",
            encoding="utf-8",
        )

        meta_personal = MemoryManager._extract_skill_meta(skill_file, is_common=False)
        assert meta_personal.is_common is False

        meta_common = MemoryManager._extract_skill_meta(skill_file, is_common=True)
        assert meta_common.is_common is True


# ── match_skills_by_description ──────────────────────────


class TestMatchSkillsByDescription:
    """Tests for match_skills_by_description()."""

    @pytest.fixture
    def skill_with_keywords(self, tmp_path: Path) -> SkillMeta:
        p = tmp_path / "cron_setup.md"
        p.write_text("dummy", encoding="utf-8")
        return SkillMeta(
            name="cron_setup",
            description="「cron設定」「定期実行」に関するスキル",
            path=p,
            is_common=False,
        )

    @pytest.fixture
    def skill_without_keywords(self, tmp_path: Path) -> SkillMeta:
        p = tmp_path / "general.md"
        p.write_text("dummy", encoding="utf-8")
        return SkillMeta(
            name="general",
            description="汎用的なスキルです",
            path=p,
            is_common=False,
        )

    def test_extract_bracket_keywords(
        self, skill_with_keywords: SkillMeta,
    ) -> None:
        """「」-delimited keywords in description trigger a match."""
        result = match_skills_by_description(
            "cron設定を確認してください", [skill_with_keywords],
        )
        assert len(result) == 1
        assert result[0].name == "cron_setup"

    def test_nfkc_normalization(self, tmp_path: Path) -> None:
        """Full-width characters match half-width equivalents via NFKC."""
        p = tmp_path / "cron.md"
        p.write_text("dummy", encoding="utf-8")
        skill = SkillMeta(
            name="cron",
            description="「cron」管理スキル",
            path=p,
            is_common=False,
        )
        # Full-width ｃｒｏｎ should match half-width cron keyword
        result = match_skills_by_description("ｃｒｏｎを設定", [skill])
        assert len(result) == 1
        assert result[0].name == "cron"

    def test_partial_match(self, skill_with_keywords: SkillMeta) -> None:
        """Partial overlap: message 'cronに追加して' matches keyword 'cron設定'
        only if 'cron設定' is a substring of the message. Here we test that
        the keyword 'cron設定' is checked as a substring of the normalized message."""
        # 'cron設定' is not a substring of 'cronに追加して' → no match
        # But '定期実行' or 'cron設定' needs to appear in the message
        result = match_skills_by_description(
            "cron設定をしてください", [skill_with_keywords],
        )
        assert len(result) == 1

    def test_no_match(self, skill_with_keywords: SkillMeta) -> None:
        """Message with no keyword overlap returns empty list."""
        result = match_skills_by_description(
            "おはよう", [skill_with_keywords],
        )
        assert result == []

    def test_skills_without_bracket_keywords_never_match(
        self, skill_without_keywords: SkillMeta,
    ) -> None:
        """Skills whose description lacks 「」 keywords are never matched."""
        result = match_skills_by_description(
            "汎用的なスキルを使って", [skill_without_keywords],
        )
        assert result == []

    def test_empty_message_returns_empty(
        self, skill_with_keywords: SkillMeta,
    ) -> None:
        """Empty message always returns an empty list."""
        result = match_skills_by_description("", [skill_with_keywords])
        assert result == []


# ── _classify_message_for_skill_budget ───────────────────


class TestClassifyMessageForSkillBudget:
    """Tests for _classify_message_for_skill_budget()."""

    def test_greeting_message(self) -> None:
        assert _classify_message_for_skill_budget("おはよう") == "greeting"

    def test_question_message(self) -> None:
        assert _classify_message_for_skill_budget("この関数はどう使うの？") == "question"

    def test_long_request_message(self) -> None:
        """Messages longer than 100 characters are classified as 'request'."""
        long_msg = "このタスクを実行してください。" * 10  # well over 100 chars
        assert len(long_msg) > 100
        assert _classify_message_for_skill_budget(long_msg) == "request"

    def test_empty_message_defaults_to_question(self) -> None:
        assert _classify_message_for_skill_budget("") == "question"


# ── _build_skill_body ────────────────────────────────────


class TestBuildSkillBody:
    """Tests for _build_skill_body()."""

    def test_file_with_frontmatter(self, tmp_path: Path) -> None:
        """Body after frontmatter delimiters is returned."""
        skill_file = tmp_path / "skill.md"
        skill_file.write_text(
            "---\n"
            "name: my-skill\n"
            "description: テスト\n"
            "---\n"
            "\n"
            "# Skill Body\n"
            "\n"
            "Do the thing.\n",
            encoding="utf-8",
        )

        body = _build_skill_body(skill_file)

        assert body.startswith("# Skill Body")
        assert "Do the thing." in body
        # Frontmatter fields must not appear in the body
        assert "name: my-skill" not in body

    def test_file_without_frontmatter(self, tmp_path: Path) -> None:
        """Full content is returned when there is no frontmatter."""
        skill_file = tmp_path / "plain.md"
        skill_file.write_text(
            "# Plain Skill\n\nJust instructions.\n",
            encoding="utf-8",
        )

        body = _build_skill_body(skill_file)

        assert body == "# Plain Skill\n\nJust instructions."
