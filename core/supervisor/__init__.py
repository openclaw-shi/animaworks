# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0
"""
Process isolation supervisor package.

Provides process-level isolation for each Anima by running them in
separate subprocesses communicating via Unix Domain Sockets.
"""

from __future__ import annotations

from core.supervisor.ipc import IPCClient, IPCEvent, IPCRequest, IPCResponse, IPCServer
from core.supervisor.manager import (
    HealthConfig,
    ProcessSupervisor,
    ReconciliationConfig,
    RestartPolicy,
)
from core.supervisor.process_handle import ProcessHandle, ProcessState, ProcessStats

__all__ = [
    "IPCClient",
    "IPCServer",
    "IPCRequest",
    "IPCResponse",
    "IPCEvent",
    "ProcessHandle",
    "ProcessState",
    "ProcessStats",
    "ProcessSupervisor",
    "RestartPolicy",
    "HealthConfig",
    "ReconciliationConfig",
]
