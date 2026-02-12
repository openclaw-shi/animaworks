from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from core.init import ensure_runtime_dir
from core.paths import get_data_dir, get_persons_dir, get_shared_dir

from core.logging_config import setup_logging

setup_logging(
    level=os.environ.get("ANIMAWORKS_LOG_LEVEL", "INFO"),
    log_dir=get_data_dir() / "logs",
)
logger = logging.getLogger("animaworks")


# ── Init ──────────────────────────────────────────────────


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize the runtime data directory from templates."""
    from core.init import merge_templates, reset_runtime_dir

    data_dir = get_data_dir()

    # --reset: complete deletion + re-initialization
    if getattr(args, "reset", False):
        if data_dir.exists():
            answer = input(
                f"WARNING: This will DELETE all data in {data_dir}\n"
                f"  (episodes, knowledge, state, config — all will be lost)\n"
                f"Continue? [yes/no]: "
            )
            if answer.strip().lower() != "yes":
                print("Aborted.")
                return
        reset_runtime_dir(data_dir)
        print(f"Runtime directory reset: {data_dir}")
        return

    # --force: safe merge (add missing files only)
    if getattr(args, "force", False):
        if not data_dir.exists():
            ensure_runtime_dir()
            print(f"Runtime directory initialized: {data_dir}")
            return
        added = merge_templates(data_dir)
        if added:
            print(f"Merged {len(added)} new file(s) from templates:")
            for f in added:
                print(f"  + {f}")
        else:
            print("Already up to date — no new template files to add.")
        return

    # Default: first-time only
    if data_dir.exists():
        print(f"Runtime directory already exists: {data_dir}")
        print("Use --force to merge new template files, or --reset to re-initialize.")
        return
    ensure_runtime_dir()
    print(f"Runtime directory initialized: {data_dir}")


# ── Legacy standalone mode ─────────────────────────────────


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the daemon (FastAPI + APScheduler) — legacy standalone mode."""
    import uvicorn

    from server.app import create_app

    ensure_runtime_dir()
    app = create_app(get_persons_dir(), get_shared_dir())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


# ── Integrated start mode ──────────────────────────────────


def cmd_start(args: argparse.Namespace) -> None:
    """Start gateway with integrated worker management (supervisor)."""
    import uvicorn

    from core.config import load_config
    from gateway.app import GatewayConfig, create_gateway_app

    ensure_runtime_dir()
    cfg = load_config()
    gw = cfg.system.gateway
    redis_url = args.redis_url or os.environ.get("ANIMAWORKS_REDIS_URL") or gw.redis_url
    host = args.host if args.host != "0.0.0.0" else gw.host
    port = args.port if args.port != 18500 else gw.port
    config = GatewayConfig(
        redis_url=redis_url,
        host=host,
        port=port,
        supervisor_enabled=True,
        supervisor_auto_restart=not args.no_auto_restart,
    )
    app = create_gateway_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


# ── Gateway mode ───────────────────────────────────────────


def cmd_gateway(args: argparse.Namespace) -> None:
    """Start the gateway process (no supervisor — for Docker/remote)."""
    import uvicorn

    from core.config import load_config
    from gateway.app import GatewayConfig, create_gateway_app

    cfg = load_config()
    gw = cfg.system.gateway
    redis_url = args.redis_url or os.environ.get("ANIMAWORKS_REDIS_URL") or gw.redis_url
    host = args.host if args.host != "0.0.0.0" else gw.host
    port = args.port if args.port != 18500 else gw.port
    config = GatewayConfig(redis_url=redis_url, host=host, port=port)
    app = create_gateway_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


# ── Worker mode ────────────────────────────────────────────


def cmd_worker(args: argparse.Namespace) -> None:
    """Start a worker process."""
    from core.config import load_config
    from worker.app import WorkerConfig, run_worker

    ensure_runtime_dir()
    cfg = load_config()
    wk = cfg.system.worker
    persons_dir = get_persons_dir()
    shared_dir = get_shared_dir()

    worker_id = args.worker_id or os.environ.get(
        "ANIMAWORKS_WORKER_ID", "worker-default"
    )
    person_names = args.persons or os.environ.get(
        "ANIMAWORKS_PERSON_NAMES", ""
    ).split(",")
    person_dirs = [
        persons_dir / name.strip() for name in person_names if name.strip()
    ]
    gateway_url = args.gateway_url or os.environ.get(
        "ANIMAWORKS_GATEWAY_URL"
    ) or wk.gateway_url
    redis_url = args.redis_url or os.environ.get("ANIMAWORKS_REDIS_URL") or wk.redis_url
    listen_port = args.port or int(
        os.environ.get("ANIMAWORKS_LISTEN_PORT", "0")
    ) or wk.listen_port

    config = WorkerConfig(
        worker_id=worker_id,
        person_dirs=person_dirs,
        shared_dir=shared_dir,
        gateway_url=gateway_url,
        redis_url=redis_url,
        listen_port=listen_port,
    )
    asyncio.run(run_worker(config))


# ── Chat ───────────────────────────────────────────────────


def cmd_chat(args: argparse.Namespace) -> None:
    """Chat with a person (via gateway or direct)."""
    if args.local:
        from core.person import DigitalPerson

        ensure_runtime_dir()
        person_dir = get_persons_dir() / args.person
        if not person_dir.exists():
            print(f"Person not found: {args.person}")
            sys.exit(1)

        person = DigitalPerson(person_dir, get_shared_dir())
        response = asyncio.run(person.process_message(args.message))
        print(response)
    else:
        import httpx

        gateway = args.gateway_url or os.environ.get(
            "ANIMAWORKS_GATEWAY_URL", "http://localhost:18500"
        )
        try:
            resp = httpx.post(
                f"{gateway}/api/persons/{args.person}/chat",
                json={"message": args.message},
                timeout=300.0,
            )
            data = resp.json()
            print(data.get("response", data.get("error", "Unknown error")))
        except httpx.ConnectError:
            print(f"Cannot connect to gateway at {gateway}. Use --local for direct mode.")
            sys.exit(1)


# ── Heartbeat ──────────────────────────────────────────────


def cmd_heartbeat(args: argparse.Namespace) -> None:
    """Trigger heartbeat (via gateway or direct)."""
    if args.local:
        from core.person import DigitalPerson

        ensure_runtime_dir()
        person_dir = get_persons_dir() / args.person
        if not person_dir.exists():
            print(f"Person not found: {args.person}")
            sys.exit(1)

        person = DigitalPerson(person_dir, get_shared_dir())
        result = asyncio.run(person.run_heartbeat())
        print(f"[{result.action}] {result.summary[:500]}")
    else:
        import httpx

        gateway = args.gateway_url or os.environ.get(
            "ANIMAWORKS_GATEWAY_URL", "http://localhost:18500"
        )
        try:
            resp = httpx.post(
                f"{gateway}/api/persons/{args.person}/trigger",
                timeout=120.0,
            )
            print(resp.json())
        except httpx.ConnectError:
            print(f"Cannot connect to gateway at {gateway}. Use --local for direct mode.")
            sys.exit(1)


# ── Send ───────────────────────────────────────────────────


def cmd_send(args: argparse.Namespace) -> None:
    """Send a message from one person to another (filesystem based)."""
    from core.messenger import Messenger

    ensure_runtime_dir()
    messenger = Messenger(get_shared_dir(), args.from_person)
    msg = messenger.send(
        to=args.to_person,
        content=args.message,
        thread_id=args.thread_id or "",
        reply_to=args.reply_to or "",
    )
    print(f"Sent: {msg.from_person} -> {msg.to_person} (id: {msg.id}, thread: {msg.thread_id})")


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
    """Show system status from gateway."""
    import httpx

    gateway = args.gateway_url or os.environ.get(
        "ANIMAWORKS_GATEWAY_URL", "http://localhost:18500"
    )
    try:
        resp = httpx.get(f"{gateway}/api/system/status", timeout=10.0)
        data = resp.json()
        print(f"Persons: {data.get('persons', 0)}")
        print(f"Workers: {data.get('workers', 0)}")
        print(f"Broker:  {data.get('broker_connected', False)}")
        for w in data.get("workers_detail", []):
            print(f"  Worker {w['worker_id']}: {w['person_names']} ({w['status']})")
        if data.get("supervisor_enabled"):
            print(f"Supervisor: enabled")
            for mw in data.get("managed_workers", []):
                pid = mw.get("pid") or "-"
                print(f"  [{mw['status']}] {mw['worker_id']} (PID {pid}, port {mw['port']})")
    except httpx.ConnectError:
        print(f"Cannot connect to gateway at {gateway}.")
        sys.exit(1)


# ── CLI Parser ─────────────────────────────────────────────


def cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="AnimaWorks - Digital Person Framework"
    )
    parser.add_argument("--gateway-url", default=None, help="Gateway URL")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override runtime data directory (default: ~/.animaworks or ANIMAWORKS_DATA_DIR)",
    )
    sub = parser.add_subparsers(dest="command")

    # Init
    p_init = sub.add_parser("init", help="Initialize runtime directory from templates")
    init_mode = p_init.add_mutually_exclusive_group()
    init_mode.add_argument(
        "--force", action="store_true",
        help="Merge missing template files into existing runtime",
    )
    init_mode.add_argument(
        "--reset", action="store_true",
        help="DELETE runtime directory and re-initialize (dangerous)",
    )
    p_init.set_defaults(func=cmd_init)

    # Start (integrated mode with supervisor)
    p_start = sub.add_parser("start", help="Start gateway + auto-managed workers")
    p_start.add_argument("--host", default="0.0.0.0")
    p_start.add_argument("--port", type=int, default=18500)
    p_start.add_argument("--redis-url", default=None, help="Redis URL")
    p_start.add_argument(
        "--no-auto-restart",
        action="store_true",
        help="Disable auto-restart of crashed workers",
    )
    p_start.set_defaults(func=cmd_start)

    # Legacy standalone
    p_serve = sub.add_parser("serve", help="Standalone mode (legacy)")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=18500)
    p_serve.set_defaults(func=cmd_serve)

    # Gateway
    p_gw = sub.add_parser("gateway", help="Start gateway process")
    p_gw.add_argument("--host", default="0.0.0.0")
    p_gw.add_argument("--port", type=int, default=18500)
    p_gw.add_argument("--redis-url", default=None, help="Redis URL")
    p_gw.set_defaults(func=cmd_gateway)

    # Worker
    p_wk = sub.add_parser("worker", help="Start worker process")
    p_wk.add_argument("--worker-id", default=None, help="Unique worker ID")
    p_wk.add_argument(
        "--persons", nargs="+", default=None, help="Person names to host"
    )
    p_wk.add_argument("--port", type=int, default=None, help="Listen port")
    p_wk.add_argument("--redis-url", default=None, help="Redis URL")
    p_wk.add_argument("--gateway-url", default=None, help="Gateway URL")
    p_wk.set_defaults(func=cmd_worker)

    # Chat
    p_chat = sub.add_parser("chat", help="Chat with a person")
    p_chat.add_argument("person", help="Person name")
    p_chat.add_argument("message", help="Message to send")
    p_chat.add_argument(
        "--local", action="store_true", help="Direct mode (no gateway)"
    )
    p_chat.set_defaults(func=cmd_chat)

    # Heartbeat
    p_hb = sub.add_parser("heartbeat", help="Trigger heartbeat")
    p_hb.add_argument("person", help="Person name")
    p_hb.add_argument(
        "--local", action="store_true", help="Direct mode (no gateway)"
    )
    p_hb.set_defaults(func=cmd_heartbeat)

    # Send
    p_send = sub.add_parser("send", help="Send message between persons")
    p_send.add_argument("from_person", help="Sender name")
    p_send.add_argument("to_person", help="Recipient name")
    p_send.add_argument("message", help="Message content")
    p_send.add_argument("--thread-id", default=None, help="Thread ID")
    p_send.add_argument("--reply-to", default=None, help="Reply to message ID")
    p_send.set_defaults(func=cmd_send)

    # List
    p_list = sub.add_parser("list", help="List all persons")
    p_list.add_argument(
        "--local", action="store_true", help="Scan filesystem directly"
    )
    p_list.set_defaults(func=cmd_list)

    # Status
    p_status = sub.add_parser("status", help="Show system status from gateway")
    p_status.set_defaults(func=cmd_status)

    # Config management
    from core.config_cli import (
        cmd_config_dispatch,
        cmd_config_get,
        cmd_config_list,
        cmd_config_set,
    )

    p_config = sub.add_parser("config", help="Manage configuration")
    p_config.add_argument(
        "--interactive", "-i", action="store_true",
        help="Interactive setup wizard",
    )
    p_config.set_defaults(func=cmd_config_dispatch, config_parser=p_config)
    config_sub = p_config.add_subparsers(dest="config_command")

    p_cfg_get = config_sub.add_parser("get", help="Get a config value")
    p_cfg_get.add_argument("key", help="Dot-notation key (e.g. system.gateway.port)")
    p_cfg_get.add_argument(
        "--show-secrets", action="store_true", help="Show API key values",
    )
    p_cfg_get.set_defaults(func=cmd_config_get)

    p_cfg_set = config_sub.add_parser("set", help="Set a config value")
    p_cfg_set.add_argument("key", help="Dot-notation key")
    p_cfg_set.add_argument("value", help="Value to set")
    p_cfg_set.set_defaults(func=cmd_config_set)

    p_cfg_list = config_sub.add_parser("list", help="List all config values")
    p_cfg_list.add_argument("--section", default=None, help="Filter by section")
    p_cfg_list.add_argument(
        "--show-secrets", action="store_true", help="Show API key values",
    )
    p_cfg_list.set_defaults(func=cmd_config_list)

    args = parser.parse_args()

    # Apply --data-dir override before any command
    if args.data_dir:
        os.environ["ANIMAWORKS_DATA_DIR"] = args.data_dir

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    cli_main()
