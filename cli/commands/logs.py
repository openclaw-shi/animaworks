"""CLI commands for viewing person logs."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def cmd_logs(args: argparse.Namespace) -> None:
    """View person logs (tail -f style)."""
    from core.paths import get_data_dir

    log_dir = get_data_dir() / "logs"

    if args.all:
        # Show all logs (server + all persons)
        _tail_all_logs(log_dir)
    else:
        # Show specific person log
        if not args.person:
            print("Error: --person is required (or use --all)")
            sys.exit(1)

        _tail_person_log(
            log_dir=log_dir,
            person_name=args.person,
            lines=args.lines,
            date=args.date
        )


def _tail_person_log(
    log_dir: Path,
    person_name: str,
    lines: int = 50,
    date: str | None = None
) -> None:
    """Tail a specific person's log file."""
    person_log_dir = log_dir / "persons" / person_name

    if not person_log_dir.exists():
        print(f"Error: No log directory for person '{person_name}'")
        print(f"Expected: {person_log_dir}")
        sys.exit(1)

    # Determine log file
    if date:
        log_file = person_log_dir / f"{date}.log"
        if not log_file.exists():
            print(f"Error: No log file for date {date}")
            sys.exit(1)
        follow = False
    else:
        # Use current.log symlink or find latest
        current_link = person_log_dir / "current.log"
        if current_link.exists():
            if current_link.is_symlink():
                log_file = person_log_dir / current_link.readlink()
            else:
                # Fallback: read text file reference
                target_name = current_link.read_text().strip()
                log_file = person_log_dir / target_name
        else:
            # Find latest log file
            log_files = sorted(
                person_log_dir.glob("*.log"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            if not log_files:
                print(f"Error: No log files found in {person_log_dir}")
                sys.exit(1)
            log_file = log_files[0]
        follow = True

    if not log_file.exists():
        print(f"Error: Log file not found: {log_file}")
        sys.exit(1)

    print(f"Tailing log: {log_file}")
    print("-" * 60)

    # Show last N lines
    _show_last_lines(log_file, lines)

    # Follow mode (like tail -f)
    if follow:
        try:
            _follow_file(log_file)
        except KeyboardInterrupt:
            print("\n[Stopped]")


def _tail_all_logs(log_dir: Path) -> None:
    """Tail all logs (server + all persons)."""
    # Find all person log directories
    persons_log_dir = log_dir / "persons"

    if not persons_log_dir.exists():
        print("No person logs found")
        return

    person_dirs = [d for d in persons_log_dir.iterdir() if d.is_dir()]

    print(f"Monitoring {len(person_dirs)} person logs")
    print("-" * 60)

    # Collect all current log files
    log_files = {}

    # Server log
    server_log = log_dir / "server.log"
    if server_log.exists():
        log_files["[SERVER]"] = server_log

    # Person logs
    for person_dir in person_dirs:
        person_name = person_dir.name
        current_link = person_dir / "current.log"

        if current_link.exists():
            if current_link.is_symlink():
                log_file = person_dir / current_link.readlink()
            else:
                target_name = current_link.read_text().strip()
                log_file = person_dir / target_name

            if log_file.exists():
                log_files[f"[{person_name}]"] = log_file

    if not log_files:
        print("No log files found")
        return

    # Show last 10 lines from each
    for prefix, log_file in log_files.items():
        print(f"\n{prefix} {log_file.name}")
        _show_last_lines(log_file, 10, prefix=prefix)

    print("\n" + "=" * 60)
    print("Following all logs... (Ctrl+C to stop)")
    print("=" * 60)

    # Follow all files
    try:
        _follow_multiple_files(log_files)
    except KeyboardInterrupt:
        print("\n[Stopped]")


def _show_last_lines(log_file: Path, n: int, prefix: str = "") -> None:
    """Show last N lines of a file."""
    try:
        lines = log_file.read_text(encoding='utf-8', errors='replace').splitlines()
        for line in lines[-n:]:
            if prefix:
                print(f"{prefix} {line}")
            else:
                print(line)
    except Exception as e:
        print(f"Error reading {log_file}: {e}")


def _follow_file(log_file: Path) -> None:
    """Follow a single log file (like tail -f)."""
    with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
        # Seek to end
        f.seek(0, 2)

        while True:
            line = f.readline()
            if line:
                print(line.rstrip())
            else:
                time.sleep(0.1)


def _follow_multiple_files(log_files: dict[str, Path]) -> None:
    """Follow multiple log files simultaneously."""
    file_handles = {}

    # Open all files and seek to end
    for prefix, log_file in log_files.items():
        try:
            f = open(log_file, 'r', encoding='utf-8', errors='replace')
            f.seek(0, 2)  # Seek to end
            file_handles[prefix] = f
        except Exception as e:
            print(f"Error opening {log_file}: {e}")

    try:
        while True:
            any_output = False

            for prefix, f in file_handles.items():
                try:
                    line = f.readline()
                    if line:
                        print(f"{prefix} {line.rstrip()}")
                        any_output = True
                except Exception:
                    pass

            if not any_output:
                time.sleep(0.1)
    finally:
        # Close all files
        for f in file_handles.values():
            try:
                f.close()
            except Exception:
                pass
