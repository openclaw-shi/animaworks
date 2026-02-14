"""Unit tests for core/person_factory.py — person creation factory."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core.person_factory import (
    BLANK_TEMPLATE_DIR,
    BOOTSTRAP_TEMPLATE,
    PERSON_TEMPLATES_DIR,
    _RUNTIME_SUBDIRS,
    _ensure_runtime_subdirs,
    _extract_name_from_md,
    _init_state_files,
    _place_bootstrap,
    _should_create_bootstrap,
    create_blank,
    create_from_md,
    create_from_template,
    list_person_templates,
    validate_person_name,
)


# ── validate_person_name ──────────────────────────────────


class TestValidatePersonName:
    def test_valid_names(self):
        assert validate_person_name("alice") is None
        assert validate_person_name("bob-smith") is None
        assert validate_person_name("charlie_01") is None
        assert validate_person_name("a") is None

    def test_empty_name(self):
        assert validate_person_name("") is not None

    def test_uppercase_rejected(self):
        assert validate_person_name("Alice") is not None

    def test_starts_with_number(self):
        assert validate_person_name("123abc") is not None

    def test_starts_with_underscore(self):
        assert validate_person_name("_test") is not None

    def test_special_chars(self):
        assert validate_person_name("a.b") is not None
        assert validate_person_name("a b") is not None
        assert validate_person_name("a@b") is not None


# ── _extract_name_from_md ─────────────────────────────────


class TestExtractNameFromMd:
    def test_character_heading(self):
        assert _extract_name_from_md("# Character: Hinata") == "hinata"

    def test_simple_heading(self):
        assert _extract_name_from_md("# Sakura") == "sakura"

    def test_eimei_pattern(self):
        assert _extract_name_from_md("英名 Hinata") == "hinata"

    def test_no_match(self):
        assert _extract_name_from_md("No heading here") is None

    def test_multiline(self):
        content = "Some intro\n# Character: Alice\nMore text"
        assert _extract_name_from_md(content) == "alice"


# ── _ensure_runtime_subdirs ───────────────────────────────


class TestEnsureRuntimeSubdirs:
    def test_creates_all_subdirs(self, tmp_path):
        person_dir = tmp_path / "person"
        person_dir.mkdir()
        _ensure_runtime_subdirs(person_dir)
        for subdir in _RUNTIME_SUBDIRS:
            assert (person_dir / subdir).is_dir()


# ── _init_state_files ─────────────────────────────────────


class TestInitStateFiles:
    def test_creates_state_files(self, tmp_path):
        person_dir = tmp_path / "person"
        (person_dir / "state").mkdir(parents=True)
        _init_state_files(person_dir)
        ct = person_dir / "state" / "current_task.md"
        assert ct.exists()
        assert ct.read_text(encoding="utf-8") == "status: idle\n"
        pending = person_dir / "state" / "pending.md"
        assert pending.exists()
        assert pending.read_text(encoding="utf-8") == ""

    def test_does_not_overwrite_existing(self, tmp_path):
        person_dir = tmp_path / "person"
        (person_dir / "state").mkdir(parents=True)
        ct = person_dir / "state" / "current_task.md"
        ct.write_text("status: busy\n", encoding="utf-8")
        _init_state_files(person_dir)
        assert ct.read_text(encoding="utf-8") == "status: busy\n"


# ── _should_create_bootstrap ──────────────────────────────


class TestShouldCreateBootstrap:
    def test_no_identity(self, tmp_path):
        """Bootstrap needed when identity.md doesn't exist."""
        person_dir = tmp_path / "person"
        person_dir.mkdir()
        assert _should_create_bootstrap(person_dir) is True

    def test_empty_identity(self, tmp_path):
        """Bootstrap needed when identity.md is empty."""
        person_dir = tmp_path / "person"
        person_dir.mkdir()
        (person_dir / "identity.md").write_text("", encoding="utf-8")
        assert _should_create_bootstrap(person_dir) is True

    def test_identity_with_undefined(self, tmp_path):
        """Bootstrap needed when identity.md contains '未定義'."""
        person_dir = tmp_path / "person"
        person_dir.mkdir()
        (person_dir / "identity.md").write_text("名前: 未定義\n職業: 未定義", encoding="utf-8")
        assert _should_create_bootstrap(person_dir) is True

    def test_character_sheet_exists(self, tmp_path):
        """Bootstrap needed when character_sheet.md exists."""
        person_dir = tmp_path / "person"
        person_dir.mkdir()
        (person_dir / "identity.md").write_text("# Defined identity", encoding="utf-8")
        (person_dir / "character_sheet.md").write_text("# Character details", encoding="utf-8")
        assert _should_create_bootstrap(person_dir) is True

    def test_defined_identity_no_bootstrap(self, tmp_path):
        """Bootstrap NOT needed when identity.md is fully defined."""
        person_dir = tmp_path / "person"
        person_dir.mkdir()
        (person_dir / "identity.md").write_text(
            "# Person Identity\n\nName: Alice\nRole: Developer",
            encoding="utf-8"
        )
        assert _should_create_bootstrap(person_dir) is False


# ── _place_bootstrap ──────────────────────────────────────


class TestPlaceBootstrap:
    def test_copies_bootstrap(self, tmp_path):
        """Bootstrap is copied when needed (no identity.md)."""
        person_dir = tmp_path / "person"
        person_dir.mkdir()
        bootstrap = tmp_path / "bootstrap.md"
        bootstrap.write_text("Bootstrap content", encoding="utf-8")
        with patch("core.person_factory.BOOTSTRAP_TEMPLATE", bootstrap):
            _place_bootstrap(person_dir)
        assert (person_dir / "bootstrap.md").exists()
        assert (person_dir / "bootstrap.md").read_text(encoding="utf-8") == "Bootstrap content"

    def test_no_bootstrap_template(self, tmp_path):
        person_dir = tmp_path / "person"
        person_dir.mkdir()
        fake = tmp_path / "nonexistent_bootstrap.md"
        with patch("core.person_factory.BOOTSTRAP_TEMPLATE", fake):
            _place_bootstrap(person_dir)
        assert not (person_dir / "bootstrap.md").exists()

    def test_skips_bootstrap_when_not_needed(self, tmp_path):
        """Bootstrap is NOT copied when identity.md is fully defined."""
        person_dir = tmp_path / "person"
        person_dir.mkdir()
        (person_dir / "identity.md").write_text(
            "# Fully Defined\n\nName: Alice\nRole: Dev",
            encoding="utf-8"
        )
        bootstrap = tmp_path / "bootstrap.md"
        bootstrap.write_text("Bootstrap content", encoding="utf-8")
        with patch("core.person_factory.BOOTSTRAP_TEMPLATE", bootstrap):
            _place_bootstrap(person_dir)
        assert not (person_dir / "bootstrap.md").exists()


# ── list_person_templates ─────────────────────────────────


class TestListPersonTemplates:
    def test_no_templates_dir(self, tmp_path):
        with patch("core.person_factory.PERSON_TEMPLATES_DIR", tmp_path / "no"):
            assert list_person_templates() == []

    def test_lists_non_underscore_dirs(self, tmp_path):
        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir()
        (tpl_dir / "_blank").mkdir()
        (tpl_dir / "dev").mkdir()
        (tpl_dir / "sales").mkdir()
        (tpl_dir / "not_a_dir.txt").write_text("file", encoding="utf-8")
        with patch("core.person_factory.PERSON_TEMPLATES_DIR", tpl_dir):
            result = list_person_templates()
            assert "dev" in result
            assert "sales" in result
            assert "_blank" not in result
            assert "not_a_dir.txt" not in result


# ── create_from_template ──────────────────────────────────


class TestCreateFromTemplate:
    def test_creates_from_template(self, tmp_path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "dev").mkdir()
        (tpl_dir / "dev" / "identity.md").write_text("I am dev", encoding="utf-8")

        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()

        with patch("core.person_factory.PERSON_TEMPLATES_DIR", tpl_dir), \
             patch("core.person_factory.BOOTSTRAP_TEMPLATE", tmp_path / "no"):
            person_dir = create_from_template(persons_dir, "dev")
            assert person_dir.exists()
            assert (person_dir / "identity.md").read_text(encoding="utf-8") == "I am dev"
            # Runtime subdirs should be created
            assert (person_dir / "episodes").is_dir()

    def test_raises_for_missing_template(self, tmp_path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        with patch("core.person_factory.PERSON_TEMPLATES_DIR", tpl_dir):
            with pytest.raises(FileNotFoundError):
                create_from_template(persons_dir, "nonexistent")

    def test_raises_for_existing_person(self, tmp_path):
        tpl_dir = tmp_path / "tpl"
        (tpl_dir / "dev").mkdir(parents=True)
        persons_dir = tmp_path / "persons"
        (persons_dir / "dev").mkdir(parents=True)
        with patch("core.person_factory.PERSON_TEMPLATES_DIR", tpl_dir):
            with pytest.raises(FileExistsError):
                create_from_template(persons_dir, "dev")

    def test_custom_name(self, tmp_path):
        tpl_dir = tmp_path / "tpl"
        (tpl_dir / "dev").mkdir(parents=True)
        (tpl_dir / "dev" / "identity.md").write_text("dev id", encoding="utf-8")
        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        with patch("core.person_factory.PERSON_TEMPLATES_DIR", tpl_dir), \
             patch("core.person_factory.BOOTSTRAP_TEMPLATE", tmp_path / "no"):
            person_dir = create_from_template(persons_dir, "dev", person_name="alice")
            assert person_dir.name == "alice"


# ── create_blank ──────────────────────────────────────────


class TestCreateBlank:
    def test_creates_blank_person(self, tmp_path):
        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        with patch("core.person_factory.BLANK_TEMPLATE_DIR", tmp_path / "no_blank"), \
             patch("core.person_factory.BOOTSTRAP_TEMPLATE", tmp_path / "no"):
            person_dir = create_blank(persons_dir, "alice")
            assert person_dir.exists()
            assert (person_dir / "episodes").is_dir()
            assert (person_dir / "state" / "current_task.md").exists()

    def test_blank_with_template(self, tmp_path):
        blank_dir = tmp_path / "blank"
        blank_dir.mkdir()
        (blank_dir / "identity.md").write_text("I am {name}", encoding="utf-8")

        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        with patch("core.person_factory.BLANK_TEMPLATE_DIR", blank_dir), \
             patch("core.person_factory.BOOTSTRAP_TEMPLATE", tmp_path / "no"):
            person_dir = create_blank(persons_dir, "bob")
            content = (person_dir / "identity.md").read_text(encoding="utf-8")
            assert content == "I am bob"

    def test_raises_for_existing(self, tmp_path):
        persons_dir = tmp_path / "persons"
        (persons_dir / "alice").mkdir(parents=True)
        with pytest.raises(FileExistsError):
            create_blank(persons_dir, "alice")


# ── create_from_md ────────────────────────────────────────


class TestCreateFromMd:
    def test_creates_from_md(self, tmp_path):
        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        md_file = tmp_path / "char.md"
        md_file.write_text("# Character: Alice\nDetails here", encoding="utf-8")

        with patch("core.person_factory.BLANK_TEMPLATE_DIR", tmp_path / "no_blank"), \
             patch("core.person_factory.BOOTSTRAP_TEMPLATE", tmp_path / "no"):
            person_dir = create_from_md(persons_dir, md_file)
            assert person_dir.name == "alice"
            assert (person_dir / "character_sheet.md").exists()
            assert "Details here" in (person_dir / "character_sheet.md").read_text(encoding="utf-8")

    def test_explicit_name(self, tmp_path):
        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        md_file = tmp_path / "char.md"
        md_file.write_text("Some content", encoding="utf-8")

        with patch("core.person_factory.BLANK_TEMPLATE_DIR", tmp_path / "no_blank"), \
             patch("core.person_factory.BOOTSTRAP_TEMPLATE", tmp_path / "no"):
            person_dir = create_from_md(persons_dir, md_file, name="bob")
            assert person_dir.name == "bob"

    def test_raises_for_missing_md(self, tmp_path):
        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            create_from_md(persons_dir, tmp_path / "nonexistent.md")

    def test_raises_for_unextractable_name(self, tmp_path):
        persons_dir = tmp_path / "persons"
        persons_dir.mkdir()
        md_file = tmp_path / "char.md"
        md_file.write_text("No heading here at all", encoding="utf-8")

        with patch("core.person_factory.BLANK_TEMPLATE_DIR", tmp_path / "no_blank"), \
             patch("core.person_factory.BOOTSTRAP_TEMPLATE", tmp_path / "no"):
            with pytest.raises(ValueError, match="Could not extract"):
                create_from_md(persons_dir, md_file)
