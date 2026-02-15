"""E2E tests for supervisor image as Vibe Transfer reference.

Tests the full flow from dispatch handler through ImageGenPipeline config
resolution, verifying that supervisor's avatar image is correctly resolved
and applied as the Vibe Transfer reference.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.config.models import AnimaWorksConfig, ImageGenConfig
from core.tooling.dispatch import _handle_generate_character_assets


@pytest.fixture
def persons_dir(data_dir: Path) -> Path:
    """Return the persons directory within the test data_dir."""
    d = data_dir / "persons"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def supervisor_with_image(persons_dir: Path) -> Path:
    """Create a supervisor person with a fullbody avatar image."""
    supervisor_dir = persons_dir / "sakura"
    assets_dir = supervisor_dir / "assets"
    assets_dir.mkdir(parents=True)
    fullbody = assets_dir / "avatar_fullbody.png"
    fullbody.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # Minimal PNG header
    return supervisor_dir


@pytest.fixture
def supervisor_without_image(persons_dir: Path) -> Path:
    """Create a supervisor person without avatar assets."""
    supervisor_dir = persons_dir / "mio"
    supervisor_dir.mkdir(parents=True)
    return supervisor_dir


@pytest.fixture
def subordinate_dir(persons_dir: Path) -> Path:
    """Create a subordinate person directory."""
    d = persons_dir / "rin"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def mock_pipeline():
    """Create a mock ImageGenPipeline that records its config."""
    mock_mod = MagicMock()
    mock_pipeline_instance = MagicMock()
    mock_result = MagicMock()
    mock_result.to_dict.return_value = {
        "fullbody_path": "assets/avatar_fullbody.png",
        "errors": [],
    }
    mock_pipeline_instance.generate_all.return_value = mock_result
    mock_mod.ImageGenPipeline.return_value = mock_pipeline_instance
    return mock_mod


class TestSupervisorVibeReferenceE2E:
    """End-to-end tests for supervisor image → Vibe Transfer reference flow."""

    def test_full_flow_supervisor_image_applied(
        self,
        data_dir: Path,
        supervisor_with_image: Path,
        subordinate_dir: Path,
        mock_pipeline: MagicMock,
    ):
        """Full flow: supervisor has image → subordinate gets it as vibe reference."""
        config = AnimaWorksConfig(
            image_gen=ImageGenConfig(
                style_prefix="anime, ",
                vibe_strength=0.8,
                vibe_info_extracted=0.7,
            ),
        )

        with patch("core.config.models.load_config", return_value=config):
            result = _handle_generate_character_assets(
                mock_pipeline,
                {
                    "person_dir": str(subordinate_dir),
                    "prompt": "1girl, short hair, blue eyes",
                    "negative_prompt": "lowres",
                    "supervisor_name": "sakura",
                },
            )

        # Verify pipeline was created with supervisor's image as style_reference
        pipeline_call = mock_pipeline.ImageGenPipeline.call_args
        config_used = pipeline_call[1]["config"]
        expected_path = str(
            supervisor_with_image / "assets" / "avatar_fullbody.png"
        )
        assert config_used.style_reference == expected_path
        # Vibe transfer settings preserved from global config
        assert config_used.vibe_strength == 0.8
        assert config_used.vibe_info_extracted == 0.7
        assert config_used.style_prefix == "anime, "

        # Verify generate_all was called with correct prompts
        gen_call = mock_pipeline.ImageGenPipeline.return_value.generate_all
        gen_call.assert_called_once_with(
            prompt="1girl, short hair, blue eyes",
            negative_prompt="lowres",
            skip_existing=True,
            steps=None,
            animations=None,
        )
        assert result == {"fullbody_path": "assets/avatar_fullbody.png", "errors": []}

    def test_full_flow_no_supervisor_image_fallback(
        self,
        data_dir: Path,
        supervisor_without_image: Path,
        subordinate_dir: Path,
        mock_pipeline: MagicMock,
    ):
        """Full flow: supervisor exists but no image → falls back to global config."""
        config = AnimaWorksConfig(
            image_gen=ImageGenConfig(
                style_reference="/global/org_style.png",
                vibe_strength=0.6,
            ),
        )

        with patch("core.config.models.load_config", return_value=config):
            _handle_generate_character_assets(
                mock_pipeline,
                {
                    "person_dir": str(subordinate_dir),
                    "prompt": "1girl",
                    "supervisor_name": "mio",
                },
            )

        pipeline_call = mock_pipeline.ImageGenPipeline.call_args
        config_used = pipeline_call[1]["config"]
        # Global style_reference preserved (supervisor has no image)
        assert config_used.style_reference == "/global/org_style.png"

    def test_full_flow_no_supervisor_specified(
        self,
        data_dir: Path,
        subordinate_dir: Path,
        mock_pipeline: MagicMock,
    ):
        """Full flow: no supervisor_name → global config used as-is."""
        config = AnimaWorksConfig(
            image_gen=ImageGenConfig(style_reference="/global/style.png"),
        )

        with patch("core.config.models.load_config", return_value=config):
            _handle_generate_character_assets(
                mock_pipeline,
                {
                    "person_dir": str(subordinate_dir),
                    "prompt": "1girl",
                },
            )

        pipeline_call = mock_pipeline.ImageGenPipeline.call_args
        config_used = pipeline_call[1]["config"]
        assert config_used is config.image_gen

    def test_supervisor_image_overrides_global_reference(
        self,
        data_dir: Path,
        supervisor_with_image: Path,
        subordinate_dir: Path,
        mock_pipeline: MagicMock,
    ):
        """Supervisor's image takes priority over global style_reference."""
        config = AnimaWorksConfig(
            image_gen=ImageGenConfig(
                style_reference="/global/org_style.png",
            ),
        )

        with patch("core.config.models.load_config", return_value=config):
            _handle_generate_character_assets(
                mock_pipeline,
                {
                    "person_dir": str(subordinate_dir),
                    "prompt": "1girl",
                    "supervisor_name": "sakura",
                },
            )

        pipeline_call = mock_pipeline.ImageGenPipeline.call_args
        config_used = pipeline_call[1]["config"]
        # Supervisor image should win over global style_reference
        expected_path = str(
            supervisor_with_image / "assets" / "avatar_fullbody.png"
        )
        assert config_used.style_reference == expected_path
        assert config_used.style_reference != "/global/org_style.png"

    def test_original_config_not_mutated(
        self,
        data_dir: Path,
        supervisor_with_image: Path,
        subordinate_dir: Path,
        mock_pipeline: MagicMock,
    ):
        """Applying supervisor image must not mutate the original ImageGenConfig."""
        original_ref = "/global/org_style.png"
        config = AnimaWorksConfig(
            image_gen=ImageGenConfig(style_reference=original_ref),
        )

        with patch("core.config.models.load_config", return_value=config):
            _handle_generate_character_assets(
                mock_pipeline,
                {
                    "person_dir": str(subordinate_dir),
                    "prompt": "1girl",
                    "supervisor_name": "sakura",
                },
            )

        # Original config object must remain unchanged
        assert config.image_gen.style_reference == original_ref

    def test_schema_includes_supervisor_name_param(self):
        """The generate_character_assets schema should include supervisor_name."""
        from core.tools.image_gen import get_tool_schemas

        schemas = get_tool_schemas()
        gen_schema = next(s for s in schemas if s["name"] == "generate_character_assets")
        props = gen_schema["input_schema"]["properties"]
        assert "supervisor_name" in props
        assert props["supervisor_name"]["type"] == "string"

    def test_multiple_subordinates_get_same_supervisor_reference(
        self,
        data_dir: Path,
        supervisor_with_image: Path,
        persons_dir: Path,
        mock_pipeline: MagicMock,
    ):
        """Multiple subordinates created by the same supervisor get same vibe reference."""
        config = AnimaWorksConfig()
        configs_used: list[ImageGenConfig] = []

        def capture_config(*args, **kwargs):
            configs_used.append(kwargs["config"])
            pipeline = MagicMock()
            result = MagicMock()
            result.to_dict.return_value = {}
            pipeline.generate_all.return_value = result
            return pipeline

        mock_pipeline.ImageGenPipeline.side_effect = capture_config

        subordinates = ["rin", "yui", "hana"]
        for name in subordinates:
            sub_dir = persons_dir / name
            sub_dir.mkdir(parents=True, exist_ok=True)

            with patch("core.config.models.load_config", return_value=config):
                _handle_generate_character_assets(
                    mock_pipeline,
                    {
                        "person_dir": str(sub_dir),
                        "prompt": "1girl",
                        "supervisor_name": "sakura",
                    },
                )

        expected_path = str(
            supervisor_with_image / "assets" / "avatar_fullbody.png"
        )
        assert len(configs_used) == 3
        for cfg in configs_used:
            assert cfg.style_reference == expected_path
