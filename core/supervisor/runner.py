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
import json
import logging
import sys
from pathlib import Path

from collections.abc import AsyncIterator
from typing import Union

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

    async def _handle_request(
        self, request: IPCRequest
    ) -> Union[IPCResponse, AsyncIterator[IPCResponse]]:
        """
        Handle incoming IPC request.

        Dispatches to appropriate handler based on method.
        For streaming requests (process_message with stream=True), returns
        an AsyncIterator[IPCResponse] instead of a single IPCResponse.
        """
        try:
            # Check for streaming process_message
            if (
                request.method == "process_message"
                and request.params.get("stream")
            ):
                return self._handle_process_message_stream(request)

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
        """Handle non-streaming process_message request."""
        if not self.person:
            raise RuntimeError("Person not initialized")

        message = params.get("message", "")
        from_person = params.get("from_person", "human")

        result = await self.person.process_message(message, from_person=from_person)

        return {
            "response": result,
            "replied_to": []
        }

    async def _handle_process_message_stream(
        self, request: IPCRequest
    ) -> AsyncIterator[IPCResponse]:
        """Handle streaming process_message request.

        Yields IPCResponse chunks with stream=True, followed by
        a final response with done=True containing the full result.
        """
        if not self.person:
            yield IPCResponse(
                id=request.id,
                error={
                    "code": "NOT_INITIALIZED",
                    "message": "Person not initialized"
                }
            )
            return

        message = request.params.get("message", "")
        from_person = request.params.get("from_person", "human")
        full_response = ""

        try:
            async for chunk in self.person.process_message_stream(
                message, from_person=from_person
            ):
                event_type = chunk.get("type", "unknown")

                if event_type == "text_delta":
                    text = chunk.get("text", "")
                    full_response += text
                    yield IPCResponse(
                        id=request.id,
                        stream=True,
                        chunk=json.dumps(chunk, ensure_ascii=False)
                    )

                elif event_type == "cycle_done":
                    cycle_result = chunk.get("cycle_result", {})
                    full_response = cycle_result.get("summary", full_response)
                    yield IPCResponse(
                        id=request.id,
                        stream=True,
                        done=True,
                        result={
                            "response": full_response,
                            "replied_to": [],
                            "cycle_result": cycle_result
                        }
                    )
                    return

                elif event_type == "error":
                    yield IPCResponse(
                        id=request.id,
                        stream=True,
                        chunk=json.dumps(chunk, ensure_ascii=False)
                    )

                else:
                    # Forward other event types (tool_start, tool_end,
                    # chain_start, etc.) as stream chunks
                    yield IPCResponse(
                        id=request.id,
                        stream=True,
                        chunk=json.dumps(chunk, ensure_ascii=False)
                    )

            # If the stream ended without a cycle_done, send final done
            yield IPCResponse(
                id=request.id,
                stream=True,
                done=True,
                result={
                    "response": full_response,
                    "replied_to": []
                }
            )

        except Exception as e:
            logger.exception(f"Error in streaming process_message: {e}")
            yield IPCResponse(
                id=request.id,
                error={
                    "code": "STREAM_ERROR",
                    "message": str(e)
                }
            )

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

def setup_logging(person_name: str, log_dir: Path) -> None:
    """Setup logging for child process with person-specific log files."""
    from core.logging_config import setup_person_logging

    setup_person_logging(
        person_name=person_name,
        log_dir=log_dir,
        level="INFO",
        also_to_console=False  # Child processes log to file only
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
    parser.add_argument(
        "--log-dir",
        required=True,
        type=Path,
        help="Path to log directory"
    )
    return parser.parse_args()


async def main() -> None:
    """Main entry point."""
    args = parse_args()

    setup_logging(args.person_name, args.log_dir)

    runner = PersonRunner(
        person_name=args.person_name,
        socket_path=args.socket_path,
        persons_dir=args.persons_dir,
        shared_dir=args.shared_dir
    )

    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
