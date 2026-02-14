"""Unit tests for core/config/models.py — Pydantic config models & load/save."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.config.models import (
    AnimaWorksConfig,
    CredentialConfig,
    GatewaySystemConfig,
    ImageGenConfig,
    PersonDefaults,
    PersonModelConfig,
    SystemConfig,
    WorkerSystemConfig,
    _match_pattern_table,
    _pattern_specificity,
    get_config_path,
    invalidate_cache,
    load_config,
    resolve_execution_mode,
    resolve_person_config,
    save_config,
)


# ── Pydantic model defaults ──────────────────────────────


class TestSystemConfig:
    def test_defaults(self):
        sc = SystemConfig()
        assert sc.mode == "server"
        assert sc.log_level == "INFO"
        assert isinstance(sc.gateway, GatewaySystemConfig)
        assert isinstance(sc.worker, WorkerSystemConfig)


class TestGatewaySystemConfig:
    def test_defaults(self):
        gc = GatewaySystemConfig()
        assert gc.host == "0.0.0.0"
        assert gc.port == 18500
        assert gc.redis_url is None
        assert gc.worker_heartbeat_timeout == 45


class TestWorkerSystemConfig:
    def test_defaults(self):
        wc = WorkerSystemConfig()
        assert wc.gateway_url == "http://localhost:18500"
        assert wc.listen_port == 18501
        assert wc.heartbeat_interval == 15


class TestCredentialConfig:
    def test_defaults(self):
        cc = CredentialConfig()
        assert cc.api_key == ""
        assert cc.base_url is None

    def test_custom(self):
        cc = CredentialConfig(api_key="sk-123", base_url="http://localhost")
        assert cc.api_key == "sk-123"
        assert cc.base_url == "http://localhost"


class TestPersonModelConfig:
    def test_all_none_by_default(self):
        pmc = PersonModelConfig()
        assert pmc.model is None
        assert pmc.fallback_model is None
        assert pmc.max_tokens is None
        assert pmc.max_turns is None
        assert pmc.credential is None
        assert pmc.context_threshold is None
        assert pmc.max_chains is None
        assert pmc.execution_mode is None
        assert pmc.supervisor is None
        assert pmc.speciality is None


class TestPersonDefaults:
    def test_defaults(self):
        pd = PersonDefaults()
        assert pd.model == "claude-sonnet-4-20250514"
        assert pd.max_tokens == 4096
        assert pd.max_turns == 20
        assert pd.credential == "anthropic"
        assert pd.context_threshold == 0.50
        assert pd.max_chains == 2
        assert pd.conversation_history_threshold == 0.30


class TestAnimaWorksConfig:
    def test_defaults(self):
        config = AnimaWorksConfig()
        assert config.version == 1
        assert isinstance(config.system, SystemConfig)
        assert "anthropic" in config.credentials
        assert config.persons == {}

    def test_roundtrip_json(self):
        config = AnimaWorksConfig()
        config.persons["alice"] = PersonModelConfig(model="gpt-4o")
        data = config.model_dump(mode="json")
        restored = AnimaWorksConfig.model_validate(data)
        assert restored.persons["alice"].model == "gpt-4o"


class TestImageGenConfig:
    def test_defaults(self):
        ic = ImageGenConfig()
        assert ic.style_reference is None
        assert ic.style_prefix == ""
        assert ic.style_suffix == ""
        assert ic.negative_prompt_extra == ""
        assert ic.vibe_strength == 0.6
        assert ic.vibe_info_extracted == 0.8

    def test_custom_values(self):
        ic = ImageGenConfig(
            style_reference="/path/to/ref.png",
            style_prefix="anime coloring, ",
            style_suffix=", high quality",
            negative_prompt_extra="realistic",
            vibe_strength=0.5,
            vibe_info_extracted=0.9,
        )
        assert ic.style_reference == "/path/to/ref.png"
        assert ic.style_prefix == "anime coloring, "
        assert ic.style_suffix == ", high quality"
        assert ic.negative_prompt_extra == "realistic"
        assert ic.vibe_strength == 0.5
        assert ic.vibe_info_extracted == 0.9

    def test_animaworks_config_has_image_gen(self):
        config = AnimaWorksConfig()
        assert isinstance(config.image_gen, ImageGenConfig)
        assert config.image_gen.style_reference is None


# ── Cache management ──────────────────────────────────────


class TestInvalidateCache:
    def test_invalidate_clears(self):
        from core.config import models
        models._config = AnimaWorksConfig()
        models._config_path = Path("/fake")
        invalidate_cache()
        assert models._config is None
        assert models._config_path is None


# ── get_config_path ───────────────────────────────────────


class TestGetConfigPath:
    def test_with_data_dir(self, tmp_path):
        result = get_config_path(tmp_path)
        assert result == tmp_path / "config.json"

    def test_without_data_dir(self, data_dir):
        result = get_config_path()
        assert result == data_dir / "config.json"


# ── load_config ───────────────────────────────────────────


class TestLoadConfig:
    @pytest.fixture(autouse=True)
    def _clear(self):
        invalidate_cache()
        yield
        invalidate_cache()

    def test_load_existing(self, data_dir):
        config = load_config(data_dir / "config.json")
        assert isinstance(config, AnimaWorksConfig)
        assert config.version == 1

    def test_load_missing_returns_default(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.json")
        assert isinstance(config, AnimaWorksConfig)

    def test_caching(self, data_dir):
        path = data_dir / "config.json"
        c1 = load_config(path)
        c2 = load_config(path)
        assert c1 is c2  # same object due to cache

    def test_invalid_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json at all", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_config(bad)

    def test_load_with_persons(self, data_dir):
        # Write a config with a person
        config_data = {
            "version": 1,
            "system": {"mode": "server", "log_level": "INFO"},
            "credentials": {"anthropic": {"api_key": ""}},
            "person_defaults": {"model": "claude-sonnet-4-20250514", "credential": "anthropic"},
            "persons": {"alice": {"model": "gpt-4o"}},
        }
        (data_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )
        invalidate_cache()
        config = load_config(data_dir / "config.json")
        assert "alice" in config.persons
        assert config.persons["alice"].model == "gpt-4o"


# ── save_config ───────────────────────────────────────────


class TestSaveConfig:
    @pytest.fixture(autouse=True)
    def _clear(self):
        invalidate_cache()
        yield
        invalidate_cache()

    def test_save_creates_file(self, tmp_path):
        config = AnimaWorksConfig()
        path = tmp_path / "config.json"
        save_config(config, path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == 1

    def test_save_sets_permissions(self, tmp_path):
        config = AnimaWorksConfig()
        path = tmp_path / "config.json"
        save_config(config, path)
        stat = path.stat()
        # 0o600 = owner read/write only
        assert stat.st_mode & 0o777 == 0o600

    def test_save_updates_cache(self, tmp_path):
        config = AnimaWorksConfig()
        path = tmp_path / "config.json"
        save_config(config, path)
        # Should be cached now
        from core.config import models
        assert models._config is config
        assert models._config_path == path

    def test_save_creates_parent_dir(self, tmp_path):
        config = AnimaWorksConfig()
        path = tmp_path / "sub" / "dir" / "config.json"
        save_config(config, path)
        assert path.exists()

    def test_save_pretty_prints(self, tmp_path):
        config = AnimaWorksConfig()
        path = tmp_path / "config.json"
        save_config(config, path)
        text = path.read_text(encoding="utf-8")
        assert "\n" in text  # pretty-printed
        assert text.endswith("\n")


# ── resolve_person_config ─────────────────────────────────


class TestResolvePersonConfig:
    def test_defaults_when_no_person_entry(self):
        config = AnimaWorksConfig()
        resolved, cred = resolve_person_config(config, "unknown")
        assert resolved.model == "claude-sonnet-4-20250514"
        assert resolved.credential == "anthropic"
        assert cred.api_key == ""

    def test_person_override(self):
        config = AnimaWorksConfig()
        config.persons["alice"] = PersonModelConfig(
            model="gpt-4o",
            max_tokens=8192,
        )
        resolved, cred = resolve_person_config(config, "alice")
        assert resolved.model == "gpt-4o"
        assert resolved.max_tokens == 8192
        # Non-overridden fields use defaults
        assert resolved.max_turns == 20

    def test_custom_credential(self):
        config = AnimaWorksConfig()
        config.credentials["openai"] = CredentialConfig(api_key="sk-openai")
        config.persons["alice"] = PersonModelConfig(credential="openai")
        resolved, cred = resolve_person_config(config, "alice")
        assert resolved.credential == "openai"
        assert cred.api_key == "sk-openai"

    def test_missing_credential_raises(self):
        config = AnimaWorksConfig()
        config.persons["alice"] = PersonModelConfig(credential="nonexistent")
        # Remove default anthropic to ensure it fails
        config.credentials = {}
        with pytest.raises(KeyError, match="nonexistent"):
            resolve_person_config(config, "alice")

    def test_partial_overrides(self):
        config = AnimaWorksConfig()
        config.persons["bob"] = PersonModelConfig(
            supervisor="alice",
        )
        resolved, _ = resolve_person_config(config, "bob")
        assert resolved.supervisor == "alice"


# ── Pattern specificity ───────────────────────────────────


class TestPatternSpecificity:
    def test_exact_match_beats_wildcard(self):
        exact = _pattern_specificity("ollama/qwen3:14b")
        wildcard = _pattern_specificity("ollama/qwen3:*")
        assert exact < wildcard  # lower = higher priority

    def test_longer_prefix_beats_shorter(self):
        long_prefix = _pattern_specificity("ollama/qwen3-coder:*")
        short_prefix = _pattern_specificity("ollama/*")
        assert long_prefix < short_prefix

    def test_exact_matches_equal_tier(self):
        a = _pattern_specificity("claude-sonnet-4-20250514")
        b = _pattern_specificity("openai/gpt-4o")
        # Both are exact — tier 0
        assert a[0] == 0
        assert b[0] == 0


# ── Pattern table matching ────────────────────────────────


class TestMatchPatternTable:
    def test_exact_match(self):
        table = {"ollama/qwen3:14b": "A2", "ollama/*": "B"}
        assert _match_pattern_table("ollama/qwen3:14b", table) == "A2"

    def test_prefix_wildcard(self):
        table = {"claude-*": "A1"}
        assert _match_pattern_table("claude-sonnet-4-20250514", table) == "A1"

    def test_suffix_wildcard(self):
        table = {"ollama/llama4:*": "A2"}
        assert _match_pattern_table("ollama/llama4:scout", table) == "A2"

    def test_partial_wildcard(self):
        table = {"ollama/glm-4.7*": "A2"}
        assert _match_pattern_table("ollama/glm-4.7:9b", table) == "A2"

    def test_no_match_returns_none(self):
        table = {"claude-*": "A1", "openai/*": "A2"}
        assert _match_pattern_table("unknown/model", table) is None

    def test_specific_pattern_beats_catchall(self):
        table = {
            "ollama/qwen3:14b": "A2",
            "ollama/*": "B",
        }
        assert _match_pattern_table("ollama/qwen3:14b", table) == "A2"
        assert _match_pattern_table("ollama/some-other", table) == "B"

    def test_empty_table_returns_none(self):
        assert _match_pattern_table("claude-sonnet-4-20250514", {}) is None

    def test_case_normalization(self):
        table = {"claude-*": "a1"}
        assert _match_pattern_table("claude-opus-4-20250514", table) == "A1"


# ── resolve_execution_mode (wildcard) ─────────────────────


class TestResolveExecutionModeWildcard:
    def test_explicit_override_autonomous(self):
        config = AnimaWorksConfig()
        assert resolve_execution_mode(config, "any-model", "autonomous") == "A2"

    def test_explicit_override_assisted(self):
        config = AnimaWorksConfig()
        assert resolve_execution_mode(config, "any-model", "assisted") == "B"

    def test_claude_wildcard_a1(self):
        config = AnimaWorksConfig()
        assert resolve_execution_mode(config, "claude-sonnet-4-20250514") == "A1"
        assert resolve_execution_mode(config, "claude-opus-4-20250514") == "A1"
        # Future Claude model also matches
        assert resolve_execution_mode(config, "claude-haiku-5-20260101") == "A1"

    def test_cloud_api_providers_a2(self):
        config = AnimaWorksConfig()
        assert resolve_execution_mode(config, "openai/gpt-4.1") == "A2"
        assert resolve_execution_mode(config, "google/gemini-2.5-pro") == "A2"
        assert resolve_execution_mode(config, "zai/zai-model") == "A2"
        assert resolve_execution_mode(config, "minimax/some-model") == "A2"
        assert resolve_execution_mode(config, "moonshot/kimi") == "A2"

    def test_ollama_a2_models(self):
        config = AnimaWorksConfig()
        assert resolve_execution_mode(config, "ollama/qwen3:14b") == "A2"
        assert resolve_execution_mode(config, "ollama/qwen3:30b") == "A2"
        assert resolve_execution_mode(config, "ollama/llama4:scout") == "A2"

    def test_ollama_b_models(self):
        config = AnimaWorksConfig()
        assert resolve_execution_mode(config, "ollama/qwen3:8b") == "B"
        assert resolve_execution_mode(config, "ollama/deepseek-r1:14b") == "B"
        assert resolve_execution_mode(config, "ollama/gemma3:27b") == "B"

    def test_unknown_model_fallback_b(self):
        config = AnimaWorksConfig()
        assert resolve_execution_mode(config, "totally/unknown-model") == "B"

    def test_config_exact_overrides_code_default(self):
        config = AnimaWorksConfig(model_modes={"ollama/qwen3:8b": "A2"})
        # Code default says B, but config.json says A2
        assert resolve_execution_mode(config, "ollama/qwen3:8b") == "A2"

    def test_config_wildcard_overrides_code_default(self):
        config = AnimaWorksConfig(model_modes={"ollama/gemma3*": "A2"})
        # Code default says B for gemma3*, but config.json overrides
        assert resolve_execution_mode(config, "ollama/gemma3:27b") == "A2"

    def test_empty_config_falls_through_to_code(self):
        config = AnimaWorksConfig(model_modes={})
        assert resolve_execution_mode(config, "claude-sonnet-4-20250514") == "A1"
        assert resolve_execution_mode(config, "openai/gpt-4.1") == "A2"
        assert resolve_execution_mode(config, "ollama/qwen3:8b") == "B"
