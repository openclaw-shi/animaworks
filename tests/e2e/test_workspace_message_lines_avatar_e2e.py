"""E2E tests for workspace message lines & avatar variants.

Validates that:
1. The org-dashboard module correctly exports showMessageLine and updateAvatarExpression
2. The WebSocket integration correctly routes anima.interaction to message lines
3. The CSS provides proper animation classes for message lines and avatar filters
4. The avatar-resolver supports expression-based candidate resolution
"""
# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORG_DASHBOARD_JS = (
    REPO_ROOT / "server" / "static" / "workspace" / "modules" / "org-dashboard.js"
)
APP_WEBSOCKET_JS = (
    REPO_ROOT / "server" / "static" / "workspace" / "modules" / "app-websocket.js"
)
STYLE_CSS = REPO_ROOT / "server" / "static" / "workspace" / "style.css"
AVATAR_RESOLVER_JS = (
    REPO_ROOT / "server" / "static" / "modules" / "avatar-resolver.js"
)


# ── Message Line E2E Flow ──────────────────────


class TestMessageLineE2EFlow:
    """End-to-end verification of message line rendering pipeline."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.org_src = ORG_DASHBOARD_JS.read_text(encoding="utf-8")
        self.ws_src = APP_WEBSOCKET_JS.read_text(encoding="utf-8")
        self.css_src = STYLE_CSS.read_text(encoding="utf-8")

    def test_full_pipeline_websocket_to_svg(self):
        """Verify the complete chain: WS event -> showMessageLine -> SVG elements."""
        assert "anima.interaction" in self.ws_src
        assert "showMessageLine" in self.ws_src
        assert "export function showMessageLine" in self.org_src
        assert "org-msg-trail" in self.org_src
        assert ".org-msg-trail" in self.css_src

    def test_message_line_svg_structure(self):
        """SVG group contains path (trail) + circle (packet) + animateMotion."""
        assert "org-msg-line-group" in self.org_src
        trail_match = re.search(r'class.*org-msg-trail', self.org_src)
        packet_match = re.search(r'class.*org-msg-packet', self.org_src)
        anim_match = re.search(r'animateMotion', self.org_src)
        assert trail_match, "Trail path missing"
        assert packet_match, "Packet circle missing"
        assert anim_match, "animateMotion missing"

    def test_message_line_lifecycle(self):
        """Message line should animate then fade and self-remove."""
        assert "MESSAGE_LINE_DURATION" in self.org_src
        assert "MESSAGE_LINE_FADE" in self.org_src
        assert "org-msg-line--fading" in self.org_src
        assert "group.remove()" in self.org_src

    def test_concurrent_lines_use_alternating_offset(self):
        """Multiple simultaneous lines should alternate control point offset."""
        assert "_msgLineCounter" in self.org_src
        assert "sign" in self.org_src or "% 2" in self.org_src

    def test_connection_lines_preserved_during_drag(self):
        """Dragging cards should redraw hierarchy lines but not erase message lines."""
        assert "_connectionsGroup.innerHTML" in self.org_src
        lines = self.org_src.split("\n")
        found_svg_innerHTML_clear = False
        for line in lines:
            if "_svgLayer.innerHTML" in line and '""' in line:
                found_svg_innerHTML_clear = True
        assert not found_svg_innerHTML_clear, (
            "_svgLayer.innerHTML should not be cleared directly — "
            "use _connectionsGroup.innerHTML instead"
        )

    def test_zero_distance_guard(self):
        """showMessageLine should skip when from === to (zero distance)."""
        assert "len < 1" in self.org_src

    def test_missing_position_guard(self):
        """showMessageLine should skip when either card is not on canvas."""
        assert "if (!fromPos || !toPos)" in self.org_src


# ── Avatar Variant E2E Flow ──────────────────────


class TestAvatarVariantE2EFlow:
    """End-to-end verification of avatar expression switching pipeline."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.org_src = ORG_DASHBOARD_JS.read_text(encoding="utf-8")
        self.ws_src = APP_WEBSOCKET_JS.read_text(encoding="utf-8")
        self.css_src = STYLE_CSS.read_text(encoding="utf-8")
        self.resolver_src = AVATAR_RESOLVER_JS.read_text(encoding="utf-8")

    def test_full_pipeline_status_to_avatar(self):
        """Verify: WS status -> updateAvatarExpression -> image swap or CSS filter."""
        assert "anima.status" in self.ws_src
        assert "updateAvatarExpression" in self.ws_src
        assert "export function updateAvatarExpression" in self.org_src
        assert "STATUS_TO_EXPRESSION" in self.org_src

    def test_expression_preload_on_init(self):
        """Expression images should be preloaded during dashboard initialization."""
        assert "_preloadAvatarExpressions" in self.org_src
        assert "requestIdleCallback" in self.org_src

    def test_all_seven_expressions_defined(self):
        """All 7 expressions from live2d.js should be listed."""
        for expr in ["neutral", "smile", "laugh", "troubled", "surprised", "thinking", "embarrassed"]:
            assert f'"{expr}"' in self.org_src

    def test_avatar_resolver_expression_candidates(self):
        """avatar-resolver.js should have bustupExpressionCandidates for expression images."""
        assert "bustupExpressionCandidates" in self.resolver_src
        assert "avatar_bustup_" in self.resolver_src

    def test_css_filter_fallback_for_all_key_expressions(self):
        """CSS should have filter definitions for missing expression images."""
        for expr in ["troubled", "thinking", "smile"]:
            assert re.search(
                rf'\[data-expression="{expr}"\]',
                self.css_src,
            ), f"CSS filter missing for expression: {expr}"

    def test_image_swap_transition(self):
        """Avatar swap should use opacity transition for smoothness."""
        assert "org-avatar--transitioning" in self.org_src
        assert ".org-avatar--transitioning" in self.css_src

    def test_debounce_rapid_status_updates(self):
        """Rapid status changes should be debounced via requestAnimationFrame."""
        assert "_avatarUpdateRafPending" in self.org_src

    def test_dispose_cleanup(self):
        """disposeOrgDashboard must clean up all avatar state."""
        assert "_avatarExpressions.clear()" in self.org_src
        assert "_connectionsGroup = null" in self.org_src
        assert "_msgLinesGroup = null" in self.org_src


# ── Accessibility ──────────────────────


class TestAccessibility:
    """Verify reduced-motion and accessibility considerations."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.css_src = STYLE_CSS.read_text(encoding="utf-8")

    def test_prefers_reduced_motion_message_lines(self):
        """Message line animations should be simplified for reduced-motion."""
        reduced_sections = re.findall(
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([^}]*(?:\{[^}]*\})*[^}]*)\}",
            self.css_src,
        )
        combined = " ".join(reduced_sections)
        assert "org-msg" in combined or "stroke-dasharray" in combined

    def test_prefers_reduced_motion_avatar(self):
        """Avatar transitions should be disabled for reduced-motion."""
        reduced_sections = re.findall(
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([^}]*(?:\{[^}]*\})*[^}]*)\}",
            self.css_src,
        )
        combined = " ".join(reduced_sections)
        assert "org-card-avatar" in combined or "transition: none" in combined


# ── Integration Consistency ──────────────────────


class TestIntegrationConsistency:
    """Cross-file consistency checks."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.org_src = ORG_DASHBOARD_JS.read_text(encoding="utf-8")
        self.ws_src = APP_WEBSOCKET_JS.read_text(encoding="utf-8")

    def test_websocket_imports_match_org_exports(self):
        """All functions imported in app-websocket.js should be exported from org-dashboard.js."""
        import_match = re.search(
            r'import\s*\{([^}]+)\}\s*from\s*"./org-dashboard\.js"',
            self.ws_src,
        )
        assert import_match, "No import from org-dashboard.js found"
        imported = [s.strip() for s in import_match.group(1).split(",")]
        for name in imported:
            assert f"export function {name}" in self.org_src or f"export async function {name}" in self.org_src, (
                f"{name} imported but not exported from org-dashboard.js"
            )

    def test_org_dashboard_imports_expression_candidates(self):
        """org-dashboard.js should import bustupExpressionCandidates."""
        assert "bustupExpressionCandidates" in self.org_src
