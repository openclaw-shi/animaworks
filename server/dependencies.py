from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

# NOTE: With process isolation, DigitalPerson instances are no longer
# in the parent process. This file provides stub dependencies for
# backwards compatibility during transition.

from typing import Any


def get_person(person_name: str) -> Any:
    """
    Stub dependency for compatibility.

    With process isolation, this should not be used.
    Routes should use ProcessSupervisor IPC instead.
    """
    raise NotImplementedError(
        "get_person() is deprecated with process isolation. "
        "Use ProcessSupervisor IPC instead."
    )
