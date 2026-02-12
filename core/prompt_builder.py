from __future__ import annotations

from pathlib import Path

from core.memory import MemoryManager
from core.paths import PROJECT_DIR, load_prompt
from core.shortterm_memory import ShortTermMemory


def _discover_other_persons(person_dir: Path) -> list[str]:
    """List sibling person directories."""
    persons_root = person_dir.parent
    self_name = person_dir.name
    others = []
    for d in sorted(persons_root.iterdir()):
        if d.is_dir() and d.name != self_name and (d / "identity.md").exists():
            others.append(d.name)
    return others


def _build_messaging_section(person_dir: Path, other_persons: list[str]) -> str:
    """Build the messaging instructions with resolved paths."""
    self_name = person_dir.name
    main_py = PROJECT_DIR / "main.py"
    persons_line = ", ".join(other_persons) if other_persons else "(まだ他の社員はいません)"

    return load_prompt(
        "messaging",
        persons_line=persons_line,
        main_py=main_py,
        self_name=self_name,
    )


def build_system_prompt(memory: MemoryManager) -> str:
    """Construct the full system prompt from Markdown files.

    System prompt =
        identity.md (who you are)
        + injection.md (role/philosophy)
        + permissions.md (what you can do)
        + state/current_task.md (what you're doing now)
        + memory directory guide
        + behavior rules (search-before-decide)
        + messaging instructions
    """
    parts: list[str] = []

    company_vision = memory.read_company_vision()
    if company_vision:
        parts.append(company_vision)

    identity = memory.read_identity()
    if identity:
        parts.append(identity)

    injection = memory.read_injection()
    if injection:
        parts.append(injection)

    permissions = memory.read_permissions()
    if permissions:
        parts.append(permissions)

    state = memory.read_current_state()
    if state:
        parts.append(f"## 現在の状態\n\n{state}")

    pending = memory.read_pending()
    if pending:
        parts.append(f"## 未完了タスク\n\n{pending}")

    # Memory directory guide
    pd = memory.person_dir
    knowledge_list = ", ".join(memory.list_knowledge_files()) or "(なし)"
    episode_list = ", ".join(memory.list_episode_files()[:7]) or "(なし)"
    procedure_list = ", ".join(memory.list_procedure_files()) or "(なし)"
    skill_summaries = memory.list_skill_summaries()
    skill_names = ", ".join(s[0] for s in skill_summaries) or "(なし)"

    parts.append(load_prompt(
        "memory_guide",
        person_dir=pd,
        knowledge_list=knowledge_list,
        episode_list=episode_list,
        procedure_list=procedure_list,
        skill_names=skill_names,
    ))

    if skill_summaries:
        skill_lines = "\n".join(
            f"| {name} | {desc} |" for name, desc in skill_summaries
        )
        parts.append(load_prompt(
            "skills_guide",
            person_dir=pd,
            skill_lines=skill_lines,
        ))

    parts.append(load_prompt("behavior_rules"))

    # Messaging instructions
    other_persons = _discover_other_persons(pd)
    parts.append(_build_messaging_section(pd, other_persons))

    return "\n\n---\n\n".join(parts)


def inject_shortterm(
    base_prompt: str,
    shortterm: ShortTermMemory,
) -> str:
    """Append short-term memory content to the system prompt.

    If the shortterm folder has a ``session_state.md``, its content is
    appended after a separator so the agent can pick up where it left off.
    """
    md_content = shortterm.load_markdown()
    if not md_content:
        return base_prompt
    return base_prompt + "\n\n---\n\n" + md_content
