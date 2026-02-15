from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.

"""Authentication data models for AnimaWorks."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AuthUser(BaseModel):
    """A human user account."""

    username: str
    display_name: str = ""
    bio: str = ""
    password_hash: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class AuthConfig(BaseModel):
    """Root authentication configuration stored in auth.json."""

    auth_mode: Literal["local_trust", "password", "multi_user"] = "local_trust"
    owner: AuthUser | None = None
    users: list[AuthUser] = []
    token_version: int = 1
