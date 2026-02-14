"""
Process handle for managing child Person processes.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from core.supervisor.ipc import IPCClient, IPCRequest, IPCResponse

logger = logging.getLogger(__name__)


# ── Process State ──────────────────────────────────────────────────

class ProcessState(Enum):
    """State of a child process."""
    STARTING = "starting"       # Process spawned, waiting for socket
    RUNNING = "running"          # Process running, socket connected
    STOPPING = "stopping"        # Shutdown requested
    STOPPED = "stopped"          # Process exited normally
    FAILED = "failed"            # Process crashed or killed
    RESTARTING = "restarting"    # Auto-restart in progress


@dataclass
class ProcessStats:
    """Process statistics."""
    started_at: datetime
    stopped_at: datetime | None = None
    restart_count: int = 0
    last_ping_at: datetime | None = None
    missed_pings: int = 0
    exit_code: int | None = None


# ── Process Handle ──────────────────────────────────────────────────

class ProcessHandle:
    """
    Handle for a child Person process.

    Manages process lifecycle (spawn, monitor, kill, restart) and
    IPC communication.
    """

    def __init__(
        self,
        person_name: str,
        socket_path: Path,
        persons_dir: Path,
        shared_dir: Path,
        log_dir: Path | None = None
    ):
        self.person_name = person_name
        self.socket_path = socket_path
        self.persons_dir = persons_dir
        self.shared_dir = shared_dir
        self.log_dir = log_dir

        self.state = ProcessState.STOPPED
        self.process: subprocess.Popen | None = None
        self.ipc_client: IPCClient | None = None
        self.stats = ProcessStats(started_at=datetime.now())

    async def start(self) -> None:
        """
        Start the child process.

        Spawns the subprocess and waits for socket connection.
        """
        if self.state not in (ProcessState.STOPPED, ProcessState.FAILED):
            raise RuntimeError(f"Cannot start process in state {self.state}")

        self.state = ProcessState.STARTING
        self.stats = ProcessStats(started_at=datetime.now())

        # Spawn child process
        cmd = [
            sys.executable,
            "-m", "core.supervisor.runner",
            "--person-name", self.person_name,
            "--socket-path", str(self.socket_path),
            "--persons-dir", str(self.persons_dir),
            "--shared-dir", str(self.shared_dir),
            "--log-dir", str(self.log_dir) if self.log_dir else "/tmp"
        ]

        logger.info(f"Starting process: {self.person_name}")
        logger.debug(f"Command: {' '.join(cmd)}")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            logger.info(f"Process started: {self.person_name} (PID {self.process.pid})")

            # Wait for socket to be created
            await self._wait_for_socket(timeout=30.0)

            # Connect IPC client
            self.ipc_client = IPCClient(self.socket_path)
            await self.ipc_client.connect(timeout=5.0)

            self.state = ProcessState.RUNNING
            logger.info(f"Process running: {self.person_name}")

        except Exception as e:
            logger.error(f"Failed to start process {self.person_name}: {e}")

            # Capture and log subprocess output if available
            if self.process:
                try:
                    stdout, stderr = self.process.communicate(timeout=1.0)
                    if stderr:
                        logger.error(f"Subprocess stderr:\n{stderr}")
                    if stdout:
                        logger.debug(f"Subprocess stdout:\n{stdout}")
                except Exception:
                    pass

            self.state = ProcessState.FAILED
            await self._cleanup()
            raise

    async def _wait_for_socket(self, timeout: float) -> None:
        """Wait for socket file to be created."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self.socket_path.exists():
                logger.debug(f"Socket file created: {self.socket_path}")
                return
            await asyncio.sleep(0.1)

        raise TimeoutError(f"Socket file not created: {self.socket_path}")

    async def send_request(
        self,
        method: str,
        params: dict,
        timeout: float = 60.0
    ) -> IPCResponse:
        """
        Send IPC request to child process.

        Args:
            method: The method name
            params: Request parameters
            timeout: Timeout in seconds

        Returns:
            The response

        Raises:
            RuntimeError: If process is not running
            asyncio.TimeoutError: If timeout exceeded
        """
        if self.state != ProcessState.RUNNING:
            raise RuntimeError(f"Process not running: {self.state}")

        if not self.ipc_client:
            raise RuntimeError("IPC client not connected")

        request = IPCRequest(
            id=f"req_{uuid.uuid4().hex[:8]}",
            method=method,
            params=params
        )

        return await self.ipc_client.send_request(request, timeout=timeout)

    async def send_request_stream(
        self,
        method: str,
        params: dict,
        timeout: float = 120.0
    ) -> AsyncIterator[IPCResponse]:
        """
        Send IPC request to child process and yield streaming responses.

        Args:
            method: The method name
            params: Request parameters (should include stream=True)
            timeout: Timeout in seconds for the entire stream

        Yields:
            IPCResponse objects (chunks and final result)

        Raises:
            RuntimeError: If process is not running
            asyncio.TimeoutError: If timeout exceeded
        """
        if self.state != ProcessState.RUNNING:
            raise RuntimeError(f"Process not running: {self.state}")

        if not self.ipc_client:
            raise RuntimeError("IPC client not connected")

        request = IPCRequest(
            id=f"req_{uuid.uuid4().hex[:8]}",
            method=method,
            params=params
        )

        async for response in self.ipc_client.send_request_stream(
            request, timeout=timeout
        ):
            yield response

    async def ping(self, timeout: float = 5.0) -> bool:
        """
        Send ping to check if process is alive.

        Returns:
            True if pong received, False otherwise
        """
        if self.state != ProcessState.RUNNING:
            return False

        try:
            response = await self.send_request("ping", {}, timeout=timeout)
            if response.error:
                logger.warning(f"Ping failed for {self.person_name}: {response.error}")
                self.stats.missed_pings += 1
                return False

            self.stats.last_ping_at = datetime.now()
            self.stats.missed_pings = 0
            return True

        except asyncio.TimeoutError:
            logger.warning(f"Ping timeout for {self.person_name}")
            self.stats.missed_pings += 1
            return False
        except Exception as e:
            logger.error(f"Ping error for {self.person_name}: {e}")
            self.stats.missed_pings += 1
            return False

    async def stop(self, timeout: float = 10.0) -> None:
        """
        Stop the child process gracefully.

        Shutdown flow:
        1. Send IPC shutdown command (wait 5s)
        2. If not exited, send SIGTERM (wait timeout/2)
        3. If still not exited, send SIGKILL

        Args:
            timeout: Total timeout in seconds for graceful shutdown
        """
        if self.state in (ProcessState.STOPPED, ProcessState.FAILED):
            logger.debug(f"Process already stopped: {self.person_name}")
            return

        self.state = ProcessState.STOPPING
        logger.info(f"Stopping process: {self.person_name}")

        if not self.process:
            self.state = ProcessState.STOPPED
            await self._cleanup()
            return

        # Step 1: Send IPC shutdown request
        try:
            logger.debug(f"Sending shutdown request to {self.person_name}")
            await self.send_request("shutdown", {}, timeout=5.0)
        except Exception as e:
            logger.warning(f"Shutdown request failed for {self.person_name}: {e}")

        # Step 2: Wait for graceful exit
        try:
            grace_period = min(timeout / 2, 5.0)
            async with asyncio.timeout(grace_period):
                while self.process.poll() is None:
                    await asyncio.sleep(0.1)

            self.stats.exit_code = self.process.returncode
            logger.info(f"Process exited gracefully: {self.person_name} (code={self.stats.exit_code})")

        except asyncio.TimeoutError:
            # Step 3: Send SIGTERM
            logger.warning(f"Process did not exit gracefully, sending SIGTERM: {self.person_name}")
            try:
                self.process.terminate()
                async with asyncio.timeout(timeout / 2):
                    while self.process.poll() is None:
                        await asyncio.sleep(0.1)

                self.stats.exit_code = self.process.returncode
                logger.info(f"Process terminated: {self.person_name} (code={self.stats.exit_code})")

            except asyncio.TimeoutError:
                # Step 4: Force SIGKILL
                logger.error(f"Process did not respond to SIGTERM, sending SIGKILL: {self.person_name}")
                await self.kill()

        self.state = ProcessState.STOPPED
        self.stats.stopped_at = datetime.now()
        await self._cleanup()

    async def kill(self) -> None:
        """Force kill the process with SIGKILL."""
        if not self.process:
            return

        logger.warning(f"Killing process: {self.person_name} (PID {self.process.pid})")
        self.process.kill()
        self.process.wait()
        self.stats.exit_code = self.process.returncode
        self.state = ProcessState.FAILED
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up resources."""
        if self.ipc_client:
            await self.ipc_client.close()
            self.ipc_client = None

        if self.socket_path.exists():
            self.socket_path.unlink()
            logger.debug(f"Socket file removed: {self.socket_path}")

    def is_alive(self) -> bool:
        """Check if process is alive."""
        if not self.process:
            return False
        return self.process.poll() is None

    def get_pid(self) -> int | None:
        """Get process PID."""
        return self.process.pid if self.process else None
