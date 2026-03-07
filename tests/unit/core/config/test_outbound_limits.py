from __future__ import annotations

"""Tests for resolve_outbound_limits and ROLE_OUTBOUND_DEFAULTS."""

import json
from pathlib import Path

from core.config.models import ROLE_OUTBOUND_DEFAULTS, resolve_outbound_limits


class TestRoleOutboundDefaults:
    """Verify the constant table has correct structure."""

    def test_all_roles_present(self):
        expected = {"manager", "engineer", "writer", "researcher", "ops", "general"}
        assert set(ROLE_OUTBOUND_DEFAULTS.keys()) == expected

    def test_all_fields_present(self):
        fields = {"max_outbound_per_hour", "max_outbound_per_day", "max_recipients_per_run"}
        for role, defaults in ROLE_OUTBOUND_DEFAULTS.items():
            assert set(defaults.keys()) == fields, f"Missing fields in {role}"

    def test_manager_values(self):
        m = ROLE_OUTBOUND_DEFAULTS["manager"]
        assert m["max_outbound_per_hour"] == 60
        assert m["max_outbound_per_day"] == 300
        assert m["max_recipients_per_run"] == 10

    def test_general_values(self):
        g = ROLE_OUTBOUND_DEFAULTS["general"]
        assert g["max_outbound_per_hour"] == 15
        assert g["max_outbound_per_day"] == 50
        assert g["max_recipients_per_run"] == 2


class TestResolveOutboundLimits:
    """Test resolve_outbound_limits with various status.json configs."""

    def test_no_anima_dir_returns_general(self):
        result = resolve_outbound_limits("test_anima", anima_dir=None)
        assert result == ROLE_OUTBOUND_DEFAULTS["general"]

    def test_missing_status_json_returns_general(self, tmp_path: Path):
        anima_dir = tmp_path / "animas" / "test"
        anima_dir.mkdir(parents=True)
        result = resolve_outbound_limits("test", anima_dir)
        assert result == ROLE_OUTBOUND_DEFAULTS["general"]

    def test_role_defaults_applied(self, tmp_path: Path):
        anima_dir = tmp_path / "animas" / "rin"
        anima_dir.mkdir(parents=True)
        (anima_dir / "status.json").write_text(json.dumps({"role": "manager", "enabled": True}), encoding="utf-8")
        result = resolve_outbound_limits("rin", anima_dir)
        assert result["max_outbound_per_hour"] == 60
        assert result["max_outbound_per_day"] == 300
        assert result["max_recipients_per_run"] == 10

    def test_engineer_role_defaults(self, tmp_path: Path):
        anima_dir = tmp_path / "animas" / "hinata"
        anima_dir.mkdir(parents=True)
        (anima_dir / "status.json").write_text(json.dumps({"role": "engineer", "enabled": True}), encoding="utf-8")
        result = resolve_outbound_limits("hinata", anima_dir)
        assert result["max_outbound_per_hour"] == 40
        assert result["max_outbound_per_day"] == 200
        assert result["max_recipients_per_run"] == 5

    def test_status_json_override_takes_priority(self, tmp_path: Path):
        anima_dir = tmp_path / "animas" / "rin"
        anima_dir.mkdir(parents=True)
        (anima_dir / "status.json").write_text(
            json.dumps(
                {
                    "role": "manager",
                    "max_outbound_per_hour": 100,
                    "max_outbound_per_day": 500,
                    "max_recipients_per_run": 8,
                }
            ),
            encoding="utf-8",
        )
        result = resolve_outbound_limits("rin", anima_dir)
        assert result["max_outbound_per_hour"] == 100
        assert result["max_outbound_per_day"] == 500
        assert result["max_recipients_per_run"] == 8

    def test_partial_override(self, tmp_path: Path):
        """Only one field overridden; others from role defaults."""
        anima_dir = tmp_path / "animas" / "rin"
        anima_dir.mkdir(parents=True)
        (anima_dir / "status.json").write_text(
            json.dumps(
                {
                    "role": "engineer",
                    "max_outbound_per_day": 999,
                }
            ),
            encoding="utf-8",
        )
        result = resolve_outbound_limits("rin", anima_dir)
        assert result["max_outbound_per_hour"] == 40  # engineer default
        assert result["max_outbound_per_day"] == 999  # overridden
        assert result["max_recipients_per_run"] == 5  # engineer default

    def test_unknown_role_falls_back_to_general(self, tmp_path: Path):
        anima_dir = tmp_path / "animas" / "custom"
        anima_dir.mkdir(parents=True)
        (anima_dir / "status.json").write_text(json.dumps({"role": "custom_role_xyz"}), encoding="utf-8")
        result = resolve_outbound_limits("custom", anima_dir)
        assert result == ROLE_OUTBOUND_DEFAULTS["general"]

    def test_no_role_field_falls_back_to_general(self, tmp_path: Path):
        anima_dir = tmp_path / "animas" / "norole"
        anima_dir.mkdir(parents=True)
        (anima_dir / "status.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
        result = resolve_outbound_limits("norole", anima_dir)
        assert result == ROLE_OUTBOUND_DEFAULTS["general"]

    def test_invalid_json_returns_general(self, tmp_path: Path):
        anima_dir = tmp_path / "animas" / "broken"
        anima_dir.mkdir(parents=True)
        (anima_dir / "status.json").write_text("not valid json", encoding="utf-8")
        result = resolve_outbound_limits("broken", anima_dir)
        assert result == ROLE_OUTBOUND_DEFAULTS["general"]

    def test_zero_value_ignored(self, tmp_path: Path):
        """Zero or negative values are treated as 'not set'."""
        anima_dir = tmp_path / "animas" / "test"
        anima_dir.mkdir(parents=True)
        (anima_dir / "status.json").write_text(
            json.dumps(
                {
                    "role": "engineer",
                    "max_outbound_per_hour": 0,
                    "max_outbound_per_day": -5,
                }
            ),
            encoding="utf-8",
        )
        result = resolve_outbound_limits("test", anima_dir)
        assert result["max_outbound_per_hour"] == 40  # engineer default (0 is invalid)
        assert result["max_outbound_per_day"] == 200  # engineer default (-5 is invalid)


class TestAnimaDefaultsFields:
    """Verify AnimaDefaults has the new outbound fields."""

    def test_fields_exist_with_none_default(self):
        from core.config.models import AnimaDefaults

        d = AnimaDefaults()
        assert d.max_outbound_per_hour is None
        assert d.max_outbound_per_day is None
        assert d.max_recipients_per_run is None
