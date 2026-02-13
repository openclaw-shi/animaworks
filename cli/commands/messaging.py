from __future__ import annotations

import argparse
import logging
import os
import sys

logger = logging.getLogger("animaworks")


# ── Send ───────────────────────────────────────────────────


def cmd_send(args: argparse.Namespace) -> None:
    """Send a message from one person to another (filesystem based)."""
    from core.init import ensure_runtime_dir
    from core.messenger import Messenger
    from core.paths import get_shared_dir

    ensure_runtime_dir()
    messenger = Messenger(get_shared_dir(), args.from_person)
    msg = messenger.send(
        to=args.to_person,
        content=args.message,
        thread_id=args.thread_id or "",
        reply_to=args.reply_to or "",
    )
    print(f"Sent: {msg.from_person} -> {msg.to_person} (id: {msg.id}, thread: {msg.thread_id})")
    _notify_server_message_sent(args.from_person, args.to_person, args.message)


def _notify_server_message_sent(
    from_person: str, to_person: str, content: str
) -> None:
    """Notify the running server about a CLI-sent message.

    Triggers WebSocket broadcast and reply tracking.
    Fails silently if the server is not running.
    """
    from cli.commands.server import _is_process_alive, _read_pid

    pid = _read_pid()
    if pid is None or not _is_process_alive(pid):
        return

    server_url = os.environ.get("ANIMAWORKS_SERVER_URL", "http://localhost:18500")
    try:
        import httpx

        resp = httpx.post(
            f"{server_url}/api/internal/message-sent",
            json={
                "from_person": from_person,
                "to_person": to_person,
                "content": content[:200],
            },
            timeout=5.0,
        )
        if resp.status_code == 200:
            logger.debug("Server notified of CLI send: %s -> %s", from_person, to_person)
        else:
            logger.debug("Server notification failed: %s", resp.status_code)
    except Exception:
        logger.debug("Could not notify server of CLI message send", exc_info=True)


# ── List ───────────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> None:
    """List all persons (from gateway or filesystem)."""
    if args.local:
        _list_local()
    else:
        import httpx

        gateway = args.gateway_url or os.environ.get(
            "ANIMAWORKS_GATEWAY_URL", "http://localhost:18500"
        )
        try:
            resp = httpx.get(f"{gateway}/api/persons", timeout=10.0)
            for p in resp.json():
                name = p.get("name", "unknown")
                status = p.get("status", "unknown")
                print(f"  {name} ({status})")
        except httpx.ConnectError:
            print("Gateway not reachable, falling back to filesystem...")
            _list_local()


def _list_local() -> None:
    from core.init import ensure_runtime_dir
    from core.paths import get_persons_dir

    ensure_runtime_dir()
    persons_dir = get_persons_dir()
    if not persons_dir.exists():
        print("No persons directory found.")
        return
    for d in sorted(persons_dir.iterdir()):
        if d.is_dir() and (d / "identity.md").exists():
            print(f"  {d.name}")


# ── Status ─────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> None:
    """Show system status."""
    import httpx

    url = args.gateway_url or os.environ.get(
        "ANIMAWORKS_GATEWAY_URL", "http://localhost:18500"
    )
    try:
        resp = httpx.get(f"{url}/api/system/status", timeout=10.0)
        data = resp.json()
        print(f"Persons: {data.get('persons', 0)}")
        print(f"Scheduler: {'running' if data.get('scheduler_running') else 'stopped'}")
        for j in data.get("jobs", []):
            print(f"  [{j['id']}] {j['name']} -> next: {j['next_run']}")
    except httpx.ConnectError:
        print(f"Cannot connect to server at {url}.")
        sys.exit(1)
