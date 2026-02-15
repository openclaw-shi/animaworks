"""Unit tests for core/auth/manager.py — Authentication configuration manager."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from core.auth.manager import get_auth_path, load_auth, save_auth
from core.auth.models import AuthConfig, AuthUser


# ── get_auth_path ────────────────────────────────────────


class TestGetAuthPath:
    def test_returns_auth_json_under_data_dir(self, data_dir: Path):
        result = get_auth_path()
        assert result == data_dir / "auth.json"

    def test_filename_is_auth_json(self, data_dir: Path):
        result = get_auth_path()
        assert result.name == "auth.json"


# ── load_auth ────────────────────────────────────────────


class TestLoadAuth:
    def test_returns_default_when_file_missing(self, data_dir: Path):
        config = load_auth()
        assert config.auth_mode == "local_trust"
        assert config.owner is None
        assert config.users == []
        assert config.token_version == 1

    def test_loads_from_file(self, data_dir: Path):
        auth_path = data_dir / "auth.json"
        auth_data = {
            "auth_mode": "password",
            "owner": {
                "username": "taro",
                "display_name": "Taro Yamada",
                "bio": "the owner",
            },
            "users": [],
            "token_version": 2,
        }
        auth_path.write_text(json.dumps(auth_data), encoding="utf-8")

        config = load_auth()
        assert config.auth_mode == "password"
        assert config.owner is not None
        assert config.owner.username == "taro"
        assert config.owner.display_name == "Taro Yamada"
        assert config.token_version == 2


# ── save_auth ────────────────────────────────────────────


class TestSaveAuth:
    def test_writes_auth_json(self, data_dir: Path):
        config = AuthConfig(
            auth_mode="password",
            owner=AuthUser(username="alice", display_name="Alice"),
        )
        save_auth(config)

        auth_path = data_dir / "auth.json"
        assert auth_path.exists()

        loaded = json.loads(auth_path.read_text(encoding="utf-8"))
        assert loaded["auth_mode"] == "password"
        assert loaded["owner"]["username"] == "alice"

    def test_sets_restrictive_permissions(self, data_dir: Path):
        config = AuthConfig()
        save_auth(config)

        auth_path = data_dir / "auth.json"
        mode = auth_path.stat().st_mode
        assert stat.S_IMODE(mode) == 0o600

    def test_creates_parent_directories(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        nested_dir = tmp_path / "deep" / "nested" / "dir"
        monkeypatch.setenv("ANIMAWORKS_DATA_DIR", str(nested_dir))

        # Invalidate caches so new env var is picked up
        from core.config import invalidate_cache
        from core.paths import _prompt_cache
        invalidate_cache()
        _prompt_cache.clear()

        config = AuthConfig()
        save_auth(config)

        auth_path = nested_dir / "auth.json"
        assert auth_path.exists()

        # Cleanup
        invalidate_cache()
        _prompt_cache.clear()

    def test_atomic_write(self, data_dir: Path):
        """Verify the file is written atomically (no .tmp leftover)."""
        config = AuthConfig(
            owner=AuthUser(username="bob"),
        )
        save_auth(config)

        auth_path = data_dir / "auth.json"
        tmp_path = auth_path.with_suffix(".tmp")
        assert auth_path.exists()
        assert not tmp_path.exists()

    def test_roundtrip(self, data_dir: Path):
        """Save and load should produce equivalent config."""
        original = AuthConfig(
            auth_mode="multi_user",
            owner=AuthUser(username="owner", display_name="Owner"),
            users=[
                AuthUser(username="user1"),
                AuthUser(username="user2", display_name="User Two"),
            ],
            token_version=3,
        )
        save_auth(original)
        loaded = load_auth()

        assert loaded.auth_mode == original.auth_mode
        assert loaded.owner is not None
        assert loaded.owner.username == original.owner.username
        assert len(loaded.users) == 2
        assert loaded.token_version == 3
