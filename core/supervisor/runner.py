"""
Child process entry point for Person subprocess.

Usage:
    python -m core.supervisor.runner \\
        --person-name sakura \\
        --socket-path ~/.animaworks/run/sockets/sakura.sock \\
        --persons-dir ~/.animaworks/persons \\
        --shared-dir ~/.animaworks/shared
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from core.person import DigitalPerson
from core.supervisor.ipc import IPCServer, IPCRequest, IPCResponse

logger = logging.getLogger(__name__)


# ── PersonRunner ──────────────────────────────────────────────────

class PersonRunner:
    """
    Runner for a single Person in a child process.

    Starts a DigitalPerson instance and exposes it via Unix socket IPC.
    """

    def __init__(
        self,
        person_name: str,
        socket_path: Path,
        persons_dir: Path,
        shared_dir: Path
    ):
        self.person_name = person_name
        self.socket_path = socket_path
        self.persons_dir = persons_dir
        self.shared_dir = shared_dir

        self.person: DigitalPerson | None = None
        self.ipc_server: IPCServer | None = None
        self.inbox_watcher_task: asyncio.Task | None = None
        self.shutdown_event = asyncio.Event()

    async def run(self) -> None:
        """
        Run the person process.

        Initializes DigitalPerson, starts IPC server, and runs until shutdown.
        """
        try:
            logger.info(f"Initializing Person: {self.person_name}")

            # Initialize DigitalPerson
            person_dir = self.persons_dir / self.person_name
            self.person = DigitalPerson(
                person_dir=person_dir,
                shared_dir=self.shared_dir
            )

            # Start IPC server
            self.ipc_server = IPCServer(
                socket_path=self.socket_path,
                request_handler=self._handle_request
            )
            await self.ipc_server.start()

            # Start inbox watcher
            self.inbox_watcher_task = asyncio.create_task(
                self._inbox_watcher_loop()
            )

            logger.info(f"Person process ready: {self.person_name}")

            # Wait for shutdown signal
            await self.shutdown_event.wait()

            logger.info(f"Shutting down: {self.person_name}")

        except Exception as e:
            logger.exception(f"Fatal error in PersonRunner: {e}")
            sys.exit(1)

        finally:
            await self._cleanup()

    async def _handle_request(self, request: IPCRequest) -> IPCResponse:
        """
        Handle incoming IPC request.

        Dispatches to appropriate handler based on method.
        """
        try:
            handler = self._get_handler(request.method)
            if not handler:
                return IPCResponse(
                    id=request.id,
                    error={
                        "code": "UNKNOWN_METHOD",
                        "message": f"Unknown method: {request.method}"
                    }
                )

            result = await handler(request.params)
            return IPCResponse(id=request.id, result=result)

        except Exception as e:
            logger.exception(f"Error handling request {request.method}: {e}")
            return IPCResponse(
                id=request.id,
                error={
                    "code": "EXECUTION_ERROR",
                    "message": str(e)
                }
            )

    def _get_handler(self, method: str):
        """Get handler for method."""
        handlers = {
            "process_message": self._handle_process_message,
            "run_heartbeat": self._handle_run_heartbeat,
            "run_cron_task": self._handle_run_cron_task,
            "get_status": self._handle_get_status,
            "ping": self._handle_ping,
            "shutdown": self._handle_shutdown,
        }
        return handlers.get(method)

    async def _handle_process_message(self, params: dict) -> dict:
        """Handle process_message request."""
        if not self.person:
            raise RuntimeError("Person not initialized")

        message = params.get("message", "")
        stream = params.get("stream", False)

        if stream:
            # Streaming not yet implemented in Phase 1
            raise NotImplementedError("Streaming not yet supported")

        result = await self.person.process_message(message)

        return {
            "response": result.response,
            "replied_to": result.replied_to
        }

    async def _handle_run_heartbeat(self, params: dict) -> dict:
        """Handle run_heartbeat request."""
        if not self.person:
            raise RuntimeError("Person not initialized")

        await self.person.run_heartbeat()

        return {"status": "completed"}

    async def _handle_run_cron_task(self, params: dict) -> dict:
        """Handle run_cron_task request."""
        if not self.person:
            raise RuntimeError("Person not initialized")

        task_name = params.get("task_name")
        task_description = params.get("task_description")

        if not task_name:
            raise ValueError("task_name is required")

        await self.person.run_cron_task(task_name, task_description)

        return {"status": "completed"}

    async def _handle_get_status(self, params: dict) -> dict:
        """Handle get_status request."""
        if not self.person:
            raise RuntimeError("Person not initialized")

        # TODO: Get actual status from Person
        return {
            "status": "idle",
            "current_task": None
        }

    async def _handle_ping(self, params: dict) -> dict:
        """Handle ping request."""
        return {
            "status": "ok",
            "person": self.person_name
        }

    async def _handle_shutdown(self, params: dict) -> dict:
        """Handle shutdown request."""
        logger.info(f"Shutdown requested for {self.person_name}")
        self.shutdown_event.set()
        return {"status": "shutting_down"}

    async def _inbox_watcher_loop(self) -> None:
        """
        Watch for incoming messages in inbox.

        Polls inbox every 2 seconds and triggers heartbeat on new messages.
        """
        if not self.person:
            return

        logger.info(f"Inbox watcher started for {self.person_name}")

        while not self.shutdown_event.is_set():
            try:
                # Check for new messages
                inbox_dir = self.shared_dir / "inbox" / self.person_name
                if inbox_dir.exists():
                    unread_messages = [
                        f for f in inbox_dir.iterdir()
                        if f.is_file() and not f.name.startswith(".")
                    ]

                    if unread_messages:
                        logger.info(
                            f"New messages detected for {self.person_name}: "
                            f"{len(unread_messages)} messages"
                        )
                        # Trigger heartbeat to process messages
                        await self.person.run_heartbeat()

                await asyncio.sleep(2.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in inbox watcher for {self.person_name}: {e}")
                await asyncio.sleep(2.0)

        logger.info(f"Inbox watcher stopped for {self.person_name}")

    async def _cleanup(self) -> None:
        """Clean up resources."""
        # Stop inbox watcher
        if self.inbox_watcher_task:
            self.inbox_watcher_task.cancel()
            try:
                await self.inbox_watcher_task
            except asyncio.CancelledError:
                pass

        # Stop IPC server
        if self.ipc_server:
            await self.ipc_server.stop()

        logger.info(f"Cleanup completed for {self.person_name}")


# ── CLI Entry Point ────────────────────────────────────────────────

def setup_logging(person_name: str) -> None:
    """Setup logging for child process."""
    # TODO: Phase 4 - Setup person-specific log file with rotation
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{person_name}] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run a Person in a subprocess"
    )
    parser.add_argument(
        "--person-name",
        required=True,
        help="Name of the person to run"
    )
    parser.add_argument(
        "--socket-path",
        required=True,
        type=Path,
        help="Path to Unix socket file"
    )
    parser.add_argument(
        "--persons-dir",
        required=True,
        type=Path,
        help="Path to persons directory"
    )
    parser.add_argument(
        "--shared-dir",
        required=True,
        type=Path,
        help="Path to shared directory"
    )
    return parser.parse_args()


async def main() -> None:
    """Main entry point."""
    args = parse_args()

    setup_logging(args.person_name)

    runner = PersonRunner(
        person_name=args.person_name,
        socket_path=args.socket_path,
        persons_dir=args.persons_dir,
        shared_dir=args.shared_dir
    )

    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
