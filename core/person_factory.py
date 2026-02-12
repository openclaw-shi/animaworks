"""Person creation factory: create new Digital Persons from templates, blank, or MD files."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from core.paths import TEMPLATES_DIR

logger = logging.getLogger("animaworks.person_factory")

PERSON_TEMPLATES_DIR = TEMPLATES_DIR / "person_templates"
BLANK_TEMPLATE_DIR = PERSON_TEMPLATES_DIR / "_blank"
BOOTSTRAP_TEMPLATE = TEMPLATES_DIR / "bootstrap.md"

# Subdirectories every person needs at runtime
_RUNTIME_SUBDIRS = [
    "episodes",
    "knowledge",
    "procedures",
    "skills",
    "state",
    "shortterm",
    "shortterm/archive",
]


def list_person_templates() -> list[str]:
    """List available person templates (excluding _blank)."""
    if not PERSON_TEMPLATES_DIR.exists():
        return []
    return [
        d.name
        for d in sorted(PERSON_TEMPLATES_DIR.iterdir())
        if d.is_dir() and not d.name.startswith("_")
    ]


def create_from_template(
    persons_dir: Path, template_name: str, *, person_name: str | None = None
) -> Path:
    """Create a person by copying a named template.

    Args:
        persons_dir: Runtime persons directory (~/.animaworks/persons/).
        template_name: Template directory name (e.g. "sakura").
        person_name: Override the directory name.  Defaults to template_name.

    Returns:
        Path to the created person directory.
    """
    template_dir = PERSON_TEMPLATES_DIR / template_name
    if not template_dir.exists():
        raise FileNotFoundError(f"Template not found: {template_name}")

    name = person_name or template_name
    person_dir = persons_dir / name
    if person_dir.exists():
        raise FileExistsError(f"Person already exists: {name}")

    shutil.copytree(template_dir, person_dir)
    _ensure_runtime_subdirs(person_dir)
    _init_state_files(person_dir)
    _place_bootstrap(person_dir)

    logger.info("Created person '%s' from template '%s'", name, template_name)
    return person_dir


def create_blank(persons_dir: Path, name: str) -> Path:
    """Create a blank person with skeleton files.

    The {name} placeholder in skeleton files is replaced with the actual name.

    Args:
        persons_dir: Runtime persons directory.
        name: Person name (lowercase alphanumeric).

    Returns:
        Path to the created person directory.
    """
    person_dir = persons_dir / name
    if person_dir.exists():
        raise FileExistsError(f"Person already exists: {name}")

    person_dir.mkdir(parents=True, exist_ok=True)

    # Copy and fill blank template files
    if BLANK_TEMPLATE_DIR.exists():
        for src in BLANK_TEMPLATE_DIR.iterdir():
            if src.is_file():
                content = src.read_text(encoding="utf-8")
                content = content.replace("{name}", name)
                (person_dir / src.name).write_text(content, encoding="utf-8")

    _ensure_runtime_subdirs(person_dir)
    _init_state_files(person_dir)
    _place_bootstrap(person_dir)

    logger.info("Created blank person '%s'", name)
    return person_dir


def create_from_md(persons_dir: Path, md_path: Path, name: str | None = None) -> Path:
    """Create a person from an MD file.

    The MD file is placed as character_sheet.md in the new person directory.
    During bootstrap, the agent reads it and populates identity.md/injection.md.

    Args:
        persons_dir: Runtime persons directory.
        md_path: Path to the source MD file.
        name: Person name.  If None, extracted from MD content.

    Returns:
        Path to the created person directory.
    """
    if not md_path.exists():
        raise FileNotFoundError(f"MD file not found: {md_path}")

    md_content = md_path.read_text(encoding="utf-8")

    if not name:
        name = _extract_name_from_md(md_content)
    if not name:
        raise ValueError(
            "Could not extract person name from MD file. "
            "Add a '# Character: name' heading or specify --name."
        )

    # Create blank skeleton first, then add character_sheet.md
    person_dir = create_blank(persons_dir, name)
    (person_dir / "character_sheet.md").write_text(md_content, encoding="utf-8")

    logger.info("Created person '%s' from MD file '%s'", name, md_path)
    return person_dir


def _extract_name_from_md(content: str) -> str | None:
    """Try to extract a person name from MD content.

    Looks for patterns like:
        # Character: Hinata
        # {name}
        英名 Hinata
    """
    # Try "# Character: Name" or "# Name"
    m = re.search(r"^#\s+(?:Character:\s*)?(\w+)", content, re.MULTILINE)
    if m:
        return m.group(1).lower()

    # Try "英名 Name"
    m = re.search(r"英名\s+(\w+)", content)
    if m:
        return m.group(1).lower()

    return None


def _ensure_runtime_subdirs(person_dir: Path) -> None:
    """Create runtime-only subdirectories."""
    for subdir in _RUNTIME_SUBDIRS:
        (person_dir / subdir).mkdir(parents=True, exist_ok=True)


def _init_state_files(person_dir: Path) -> None:
    """Create initial state files if they don't exist."""
    current_task = person_dir / "state" / "current_task.md"
    if not current_task.exists():
        current_task.write_text("status: idle\n", encoding="utf-8")

    pending = person_dir / "state" / "pending.md"
    if not pending.exists():
        pending.write_text("", encoding="utf-8")


def _place_bootstrap(person_dir: Path) -> None:
    """Copy the bootstrap template into the person directory."""
    if BOOTSTRAP_TEMPLATE.exists():
        shutil.copy2(BOOTSTRAP_TEMPLATE, person_dir / "bootstrap.md")
        logger.debug("Placed bootstrap.md in %s", person_dir)


def validate_person_name(name: str) -> str | None:
    """Validate a person name.  Returns error message or None if valid."""
    if not name:
        return "Name cannot be empty"
    if not re.match(r"^[a-z][a-z0-9_-]*$", name):
        return "Name must be lowercase alphanumeric (a-z, 0-9, -, _), starting with a letter"
    if name.startswith("_"):
        return "Name cannot start with underscore"
    return None
