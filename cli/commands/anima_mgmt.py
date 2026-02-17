"""CLI commands for anima process management."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_anima_restart(args: argparse.Namespace) -> None:
    """Restart a specific anima process."""
    import requests

    from core.paths import get_data_dir

    # Check if server is running
    pid_file = get_data_dir() / "server.pid"

    if not pid_file.exists():
        print("Error: Server is not running")
        sys.exit(1)

    # Use gateway URL if provided, otherwise default to localhost
    gateway_url = args.gateway_url or "http://localhost:18500"

    try:
        response = requests.post(
            f"{gateway_url}/api/animas/{args.anima}/restart",
            timeout=30.0
        )
        response.raise_for_status()
        result = response.json()
        print(f"Anima '{args.anima}' restarted successfully")
        print(f"PID: {result.get('pid', 'N/A')}")
    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to restart anima: {e}")
        sys.exit(1)


def cmd_anima_status(args: argparse.Namespace) -> None:
    """Show status of anima processes."""
    import requests

    from core.paths import get_data_dir

    # Check if server is running
    pid_file = get_data_dir() / "server.pid"

    if not pid_file.exists():
        print("Server is not running")
        return

    # Read PID
    try:
        server_pid = int(pid_file.read_text().strip())
        print(f"Server PID: {server_pid}")
    except Exception:
        print("Server PID file corrupted")

    # Use gateway URL if provided
    gateway_url = args.gateway_url or "http://localhost:18500"

    try:
        # Get status from API
        if args.anima:
            # Specific anima
            response = requests.get(
                f"{gateway_url}/api/animas/{args.anima}",
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            _print_anima_status(args.anima, data.get("status", {}))
        else:
            # All animas
            response = requests.get(
                f"{gateway_url}/api/animas",
                timeout=10.0
            )
            response.raise_for_status()
            animas = response.json()

            print(f"\nTotal animas: {len(animas)}")
            print("-" * 60)

            for anima in animas:
                name = anima.get("name", "unknown")
                # Get individual status
                try:
                    status_resp = requests.get(
                        f"{gateway_url}/api/animas/{name}",
                        timeout=5.0
                    )
                    status_resp.raise_for_status()
                    data = status_resp.json()
                    _print_anima_status(name, data.get("status", {}))
                except Exception as e:
                    print(f"\n{name}:")
                    print(f"  Status: ERROR ({e})")
                print()

    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to get status: {e}")
        sys.exit(1)


def _print_anima_status(name: str, status: dict) -> None:
    """Print formatted anima status."""
    print(f"\n{name}:")
    print(f"  State: {status.get('state', 'unknown')}")
    print(f"  PID: {status.get('pid', 'N/A')}")
    print(f"  Status: {status.get('status', 'unknown')}")

    if status.get('uptime_sec'):
        uptime = status['uptime_sec']
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)
        print(f"  Uptime: {hours}h {minutes}m {seconds}s")

    if status.get('restart_count'):
        print(f"  Restarts: {status['restart_count']}")

    if status.get('current_task'):
        print(f"  Current task: {status['current_task']}")
