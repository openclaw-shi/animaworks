"""Tests for core.tooling.schemas — canonical tool schema definitions and converters."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import core.tools
from core.tooling.schemas import (
    FILE_TOOLS,
    MEMORY_TOOLS,
    build_tool_list,
    load_external_schemas,
    to_anthropic_format,
    to_litellm_format,
)


# ── Canonical schema structure ─────────────────────────────────


class TestMemoryTools:
    def test_memory_tools_is_list(self):
        assert isinstance(MEMORY_TOOLS, list)
        assert len(MEMORY_TOOLS) == 4

    def test_search_memory_schema(self):
        schema = next(t for t in MEMORY_TOOLS if t["name"] == "search_memory")
        assert "description" in schema
        assert schema["parameters"]["type"] == "object"
        assert "query" in schema["parameters"]["properties"]
        assert "query" in schema["parameters"]["required"]

    def test_read_memory_file_schema(self):
        schema = next(t for t in MEMORY_TOOLS if t["name"] == "read_memory_file")
        assert "path" in schema["parameters"]["properties"]
        assert "path" in schema["parameters"]["required"]

    def test_write_memory_file_schema(self):
        schema = next(t for t in MEMORY_TOOLS if t["name"] == "write_memory_file")
        props = schema["parameters"]["properties"]
        assert "path" in props
        assert "content" in props
        assert "mode" in props
        assert set(schema["parameters"]["required"]) == {"path", "content"}

    def test_send_message_schema(self):
        schema = next(t for t in MEMORY_TOOLS if t["name"] == "send_message")
        props = schema["parameters"]["properties"]
        assert "to" in props
        assert "content" in props
        assert set(schema["parameters"]["required"]) == {"to", "content"}


class TestFileTools:
    def test_file_tools_is_list(self):
        assert isinstance(FILE_TOOLS, list)
        assert len(FILE_TOOLS) == 4

    def test_read_file_schema(self):
        schema = next(t for t in FILE_TOOLS if t["name"] == "read_file")
        assert "path" in schema["parameters"]["properties"]

    def test_write_file_schema(self):
        schema = next(t for t in FILE_TOOLS if t["name"] == "write_file")
        assert set(schema["parameters"]["required"]) == {"path", "content"}

    def test_edit_file_schema(self):
        schema = next(t for t in FILE_TOOLS if t["name"] == "edit_file")
        assert set(schema["parameters"]["required"]) == {"path", "old_string", "new_string"}

    def test_execute_command_schema(self):
        schema = next(t for t in FILE_TOOLS if t["name"] == "execute_command")
        assert "command" in schema["parameters"]["properties"]
        assert "timeout" in schema["parameters"]["properties"]


# ── Format converters ─────────────────────────────────────────


class TestToAnthropicFormat:
    def test_converts_single_tool(self):
        tools = [{"name": "foo", "description": "desc", "parameters": {"type": "object"}}]
        result = to_anthropic_format(tools)
        assert len(result) == 1
        assert result[0]["name"] == "foo"
        assert result[0]["description"] == "desc"
        assert result[0]["input_schema"] == {"type": "object"}
        assert "parameters" not in result[0]

    def test_converts_multiple_tools(self):
        result = to_anthropic_format(MEMORY_TOOLS)
        assert len(result) == len(MEMORY_TOOLS)
        for item in result:
            assert "name" in item
            assert "description" in item
            assert "input_schema" in item

    def test_empty_list(self):
        assert to_anthropic_format([]) == []


class TestToLitellmFormat:
    def test_converts_single_tool(self):
        tools = [{"name": "bar", "description": "desc2", "parameters": {"type": "object"}}]
        result = to_litellm_format(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "bar"
        assert result[0]["function"]["description"] == "desc2"
        assert result[0]["function"]["parameters"] == {"type": "object"}

    def test_converts_multiple_tools(self):
        result = to_litellm_format(FILE_TOOLS)
        assert len(result) == len(FILE_TOOLS)
        for item in result:
            assert item["type"] == "function"
            assert "name" in item["function"]

    def test_empty_list(self):
        assert to_litellm_format([]) == []


# ── build_tool_list ───────────────────────────────────────────


class TestBuildToolList:
    def test_default_returns_memory_tools_only(self):
        result = build_tool_list()
        names = [t["name"] for t in result]
        assert "search_memory" in names
        assert "read_memory_file" in names
        assert "write_memory_file" in names
        assert "send_message" in names
        assert "read_file" not in names

    def test_include_file_tools(self):
        result = build_tool_list(include_file_tools=True)
        names = [t["name"] for t in result]
        assert "read_file" in names
        assert "write_file" in names
        assert "edit_file" in names
        assert "execute_command" in names

    def test_include_external_schemas(self):
        ext = [{"name": "custom_tool", "description": "custom", "parameters": {}}]
        result = build_tool_list(external_schemas=ext)
        names = [t["name"] for t in result]
        assert "custom_tool" in names

    def test_combined(self):
        ext = [{"name": "ext1", "description": "e", "parameters": {}}]
        result = build_tool_list(
            include_file_tools=True,
            external_schemas=ext,
        )
        names = [t["name"] for t in result]
        assert "search_memory" in names
        assert "read_file" in names
        assert "ext1" in names

    def test_does_not_mutate_memory_tools(self):
        original_len = len(MEMORY_TOOLS)
        build_tool_list(include_file_tools=True)
        assert len(MEMORY_TOOLS) == original_len


# ── load_external_schemas ─────────────────────────────────────


class TestLoadExternalSchemas:
    def test_empty_registry(self):
        assert load_external_schemas([]) == []

    def test_unknown_tool_name(self):
        result = load_external_schemas(["nonexistent_tool_xyz"])
        assert result == []

    def test_loads_schemas_from_module(self):
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [
            {
                "name": "web_search",
                "description": "Search the web",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            }
        ]

        with patch.dict(core.tools.TOOL_MODULES, {"web_search": "core.tools.web_search"}, clear=True), \
             patch("importlib.import_module", return_value=mock_mod):
            result = load_external_schemas(["web_search"])

        assert len(result) == 1
        assert result[0]["name"] == "web_search"
        assert result[0]["parameters"] == {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        }

    def test_handles_module_without_get_tool_schemas(self):
        mock_mod = MagicMock(spec=[])  # No get_tool_schemas attribute

        with patch.dict(core.tools.TOOL_MODULES, {"web_search": "core.tools.web_search"}, clear=True), \
             patch("importlib.import_module", return_value=mock_mod):
            result = load_external_schemas(["web_search"])

        assert result == []

    def test_handles_import_error(self):
        with patch.dict(core.tools.TOOL_MODULES, {"web_search": "core.tools.web_search"}, clear=True), \
             patch("importlib.import_module", side_effect=ImportError("no module")):
            result = load_external_schemas(["web_search"])

        assert result == []

    def test_skips_tool_not_in_registry(self):
        with patch.dict(core.tools.TOOL_MODULES, {"web_search": "core.tools.web_search"}, clear=True):
            result = load_external_schemas(["slack"])

        assert result == []

    def test_uses_parameters_key_as_fallback(self):
        mock_mod = MagicMock()
        mock_mod.get_tool_schemas.return_value = [
            {
                "name": "test_tool",
                "description": "Test",
                "parameters": {"type": "object", "properties": {}},
            }
        ]

        with patch.dict(core.tools.TOOL_MODULES, {"test": "core.tools.test"}, clear=True), \
             patch("importlib.import_module", return_value=mock_mod):
            result = load_external_schemas(["test"])

        assert len(result) == 1
        assert result[0]["parameters"] == {"type": "object", "properties": {}}
