from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

# NOTE: With process isolation, DigitalPerson instances are no longer
# in the parent process. All routes should use ProcessSupervisor IPC
# or read files directly from disk instead of using get_person dependency.
#
# This file is kept for reference but the dependency is no longer used.
