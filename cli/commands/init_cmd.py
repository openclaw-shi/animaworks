from __future__ import annotations

import argparse
import sys


# ── Init ──────────────────────────────────────────────────


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize the runtime data directory from templates."""
    from pathlib import Path

    from core.init import ensure_runtime_dir, merge_templates, reset_runtime_dir
    from core.paths import get_data_dir
    from core.person_factory import (
        create_blank,
        create_from_md,
        create_from_template,
        validate_person_name,
    )

    from cli.commands.server import (
        _clear_pycache,
        _is_process_alive,
        _read_pid,
        _stop_server,
        cmd_start,
    )

    data_dir = get_data_dir()

    # --reset: complete deletion + re-initialization (interactive)
    if getattr(args, "reset", False):
        # Stop running server before reset (PID file will be deleted with data dir)
        pid = _read_pid()
        was_running = pid is not None and _is_process_alive(pid)
        if was_running:
            print("Stopping running server before reset...")
            if not _stop_server():
                print("Error: Cannot reset — failed to stop the running server.")
                return

        if data_dir.exists():
            answer = input(
                f"WARNING: This will DELETE all data in {data_dir}\n"
                f"  (episodes, knowledge, state, config — all will be lost)\n"
                f"Continue? [yes/no]: "
            )
            if answer.strip().lower() != "yes":
                print("Aborted.")
                return
        reset_runtime_dir(data_dir, skip_persons=True)
        print(f"Runtime directory reset: {data_dir}")
        _interactive_person_setup(data_dir)
        _interactive_user_setup(data_dir)

        # Restart server if it was running before reset
        if was_running:
            print("\nRestarting server...")
            removed = _clear_pycache()
            if removed:
                print(f"Cleared {removed} __pycache__ directories.")
            start_args = argparse.Namespace(host="0.0.0.0", port=18500)
            cmd_start(start_args)
        return

    # --force: safe merge (add missing files only)
    if getattr(args, "force", False):
        if not data_dir.exists():
            ensure_runtime_dir(skip_persons=True)
            print(f"Runtime directory initialized: {data_dir}")
            _interactive_person_setup(data_dir)
            _interactive_user_setup(data_dir)
            return
        added = merge_templates(data_dir)
        if added:
            print(f"Merged {len(added)} new file(s) from templates:")
            for f in added:
                print(f"  + {f}")
        else:
            print("Already up to date — no new template files to add.")
        return

    # Non-interactive shortcuts
    # Always call ensure_runtime_dir — it's idempotent (checks config.json).
    persons_dir = data_dir / "persons"

    if getattr(args, "template", None):
        ensure_runtime_dir(skip_persons=True)
        persons_dir.mkdir(parents=True, exist_ok=True)
        person_dir = create_from_template(persons_dir, args.template)
        _register_person_in_config(data_dir, person_dir.name)
        print(f"Created person '{person_dir.name}' from template '{args.template}'")
        return

    if getattr(args, "from_md", None):
        ensure_runtime_dir(skip_persons=True)
        persons_dir.mkdir(parents=True, exist_ok=True)
        md_path = Path(args.from_md).resolve()
        person_dir = create_from_md(
            persons_dir, md_path, name=getattr(args, "name", None)
        )
        _register_person_in_config(data_dir, person_dir.name)
        print(f"Created person '{person_dir.name}' from {md_path.name}")
        return

    if getattr(args, "blank", None):
        ensure_runtime_dir(skip_persons=True)
        persons_dir.mkdir(parents=True, exist_ok=True)
        err = validate_person_name(args.blank)
        if err:
            print(f"Error: {err}")
            sys.exit(1)
        person_dir = create_blank(persons_dir, args.blank)
        _register_person_in_config(data_dir, person_dir.name)
        print(f"Created blank person '{person_dir.name}'")
        return

    if getattr(args, "skip_person", False):
        ensure_runtime_dir(skip_persons=True)
        print(f"Runtime directory initialized (no persons): {data_dir}")
        return

    # Default: interactive first-time setup
    # Use config.json as the proper initialization marker
    config_json = data_dir / "config.json"
    if config_json.exists():
        print(f"Runtime directory already exists: {data_dir}")
        print("Use --force to merge new template files, or --reset to re-initialize.")
        return

    ensure_runtime_dir(skip_persons=True)
    print(f"Runtime directory initialized: {data_dir}")
    _interactive_person_setup(data_dir)
    _interactive_user_setup(data_dir)


def _interactive_person_setup(data_dir) -> None:
    """Interactive person creation during init."""
    from pathlib import Path

    from core.person_factory import (
        create_blank,
        create_from_md,
        create_from_template,
        list_person_templates,
        validate_person_name,
    )

    persons_dir = data_dir / "persons"
    persons_dir.mkdir(parents=True, exist_ok=True)

    templates = list_person_templates()

    # テンプレートがない場合: 名前から直接作成
    if not templates:
        print()
        name = input(
            "最初のDigital Personの名前（英小文字、空欄でスキップ）: "
        ).strip()
        if not name:
            print("パーソンの作成をスキップしました。")
            return
        err = validate_person_name(name)
        if err:
            print(f"Error: {err}")
            return
        person_dir = create_blank(persons_dir, name)
        _register_person_in_config(data_dir, person_dir.name)
        print(f"\n{person_dir.name} を作成しました。")
        return

    # テンプレートがある場合: メニュー表示
    template_list = ", ".join(templates)

    print()
    print("最初のDigital Personをどのように作成しますか？")
    print(f"  1. テンプレートから作成 ({template_list})")
    print("  2. MDファイルから作成")
    print("  3. ブランクで作成（名前のみ指定）")
    print("  4. スキップ（後で作成）")

    choice = input("\n選択 [1]: ").strip() or "1"

    if choice == "1":
        if len(templates) == 1:
            tpl = templates[0]
        else:
            print(f"\n利用可能なテンプレート:")
            for i, t in enumerate(templates, 1):
                print(f"  {i}. {t}")
            idx = input(f"番号 [1]: ").strip() or "1"
            try:
                tpl = templates[int(idx) - 1]
            except (ValueError, IndexError):
                tpl = templates[0]
        person_dir = create_from_template(persons_dir, tpl)
        _register_person_in_config(data_dir, person_dir.name)
        print(f"\n{person_dir.name} を作成しました。")
        return

    if choice == "2":
        md_path_str = input("MDファイルのパス: ").strip()
        if not md_path_str:
            print("スキップしました。")
            return
        md_path = Path(md_path_str).expanduser().resolve()
        if not md_path.exists():
            print(f"ファイルが見つかりません: {md_path}")
            return
        name = input("パーソン名（英小文字、空欄で自動検出）: ").strip() or None
        if name:
            err = validate_person_name(name)
            if err:
                print(f"Error: {err}")
                return
        try:
            person_dir = create_from_md(persons_dir, md_path, name=name)
            _register_person_in_config(data_dir, person_dir.name)
            print(f"\n{person_dir.name} を作成しました。")
        except ValueError as e:
            print(f"Error: {e}")
        return

    if choice == "3":
        name = input("パーソン名（英小文字）: ").strip()
        if not name:
            print("スキップしました。")
            return
        err = validate_person_name(name)
        if err:
            print(f"Error: {err}")
            return
        person_dir = create_blank(persons_dir, name)
        _register_person_in_config(data_dir, person_dir.name)
        print(f"\n{person_dir.name} を作成しました。")
        return

    # choice == "4" or anything else
    print("パーソンの作成をスキップしました。")


def _interactive_user_setup(data_dir) -> None:
    """Optionally collect user info during init."""
    print()
    answer = input("あなたの情報を登録しますか？ (パーソンがあなたを覚えます) [Y/n]: ").strip()
    if answer.lower() in ("n", "no"):
        return

    user_name = input("  お名前: ").strip()
    if not user_name:
        return

    timezone = input("  タイムゾーン [Asia/Tokyo]: ").strip() or "Asia/Tokyo"
    notes = input("  メモ（任意）: ").strip()

    # Create user directory following the behavior_rules.md structure
    user_dir = data_dir / "shared" / "users" / user_name
    user_dir.mkdir(parents=True, exist_ok=True)

    index_content = (
        f"# {user_name}\n\n"
        f"## 基本情報\n"
        f"- 名前: {user_name}\n"
        f"- タイムゾーン: {timezone}\n"
    )
    if notes:
        index_content += f"\n## 重要な好み・傾向\n{notes}\n"
    else:
        index_content += "\n## 重要な好み・傾向\n\n"
    index_content += "\n## 注意事項\n\n"

    (user_dir / "index.md").write_text(index_content, encoding="utf-8")
    (user_dir / "log.md").write_text("", encoding="utf-8")

    print(f"\nユーザー情報を保存しました: {user_dir}/index.md")


def _register_person_in_config(data_dir, person_name: str) -> None:
    """Register a newly created person in config.json."""
    from core.config import PersonModelConfig, load_config, save_config

    config_path = data_dir / "config.json"
    if not config_path.exists():
        return
    config = load_config(config_path)
    if person_name not in config.persons:
        config.persons[person_name] = PersonModelConfig()
        save_config(config, config_path)
