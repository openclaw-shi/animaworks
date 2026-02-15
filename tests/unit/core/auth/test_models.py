"""Unit tests for core/auth/models.py — Authentication data models."""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from core.auth.models import AuthConfig, AuthUser


# ── AuthUser ─────────────────────────────────────────────


class TestAuthUser:
    def test_create_with_defaults(self):
        user = AuthUser(username="alice")
        assert user.username == "alice"
        assert user.display_name == ""
        assert user.bio == ""
        assert user.password_hash is None
        assert isinstance(user.created_at, datetime)

    def test_all_fields(self):
        now = datetime(2026, 2, 15, 12, 0, 0)
        user = AuthUser(
            username="bob",
            display_name="Bob Smith",
            bio="A test user",
            password_hash="hashed_pw_123",
            created_at=now,
        )
        assert user.username == "bob"
        assert user.display_name == "Bob Smith"
        assert user.bio == "A test user"
        assert user.password_hash == "hashed_pw_123"
        assert user.created_at == now

    def test_password_hash_defaults_to_none(self):
        user = AuthUser(username="carol")
        assert user.password_hash is None

    def test_created_at_is_auto_set(self):
        before = datetime.now()
        user = AuthUser(username="dave")
        after = datetime.now()
        assert before <= user.created_at <= after


# ── AuthConfig ───────────────────────────────────────────


class TestAuthConfig:
    def test_defaults(self):
        config = AuthConfig()
        assert config.auth_mode == "local_trust"
        assert config.owner is None
        assert config.users == []
        assert config.token_version == 1

    def test_with_owner_set(self):
        owner = AuthUser(username="admin", display_name="Admin User")
        config = AuthConfig(owner=owner)
        assert config.owner is not None
        assert config.owner.username == "admin"
        assert config.owner.display_name == "Admin User"

    def test_auth_mode_local_trust(self):
        config = AuthConfig(auth_mode="local_trust")
        assert config.auth_mode == "local_trust"

    def test_auth_mode_password(self):
        config = AuthConfig(auth_mode="password")
        assert config.auth_mode == "password"

    def test_auth_mode_multi_user(self):
        config = AuthConfig(auth_mode="multi_user")
        assert config.auth_mode == "multi_user"

    def test_auth_mode_invalid_rejected(self):
        with pytest.raises(ValidationError):
            AuthConfig(auth_mode="invalid_mode")

    def test_users_list(self):
        users = [
            AuthUser(username="alice"),
            AuthUser(username="bob"),
        ]
        config = AuthConfig(users=users)
        assert len(config.users) == 2
        assert config.users[0].username == "alice"
        assert config.users[1].username == "bob"

    def test_token_version_custom(self):
        config = AuthConfig(token_version=5)
        assert config.token_version == 5
