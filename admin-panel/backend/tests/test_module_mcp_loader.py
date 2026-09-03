"""Tests for services.module_mcp_loader.register_module_mcp_tools."""
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP


@pytest.fixture
def db(clean_db):
    from core.db import get_db
    conn = get_db()
    yield conn
    conn.close()


def _enable_module(db, module_id: str, enabled_at: str) -> None:
    db.execute(
        "INSERT INTO modules_enabled (module_id, enabled_at) VALUES (?, ?)",
        (module_id, enabled_at),
    )
    db.commit()


def _make_module(root: Path, module_id: str, mcp_module_source: str | None = None) -> Path:
    mod_dir = root / module_id
    mod_dir.mkdir(parents=True)
    (mod_dir / "SKILL.md").write_text(f"---\nname: {module_id}\n---\n")
    if mcp_module_source is not None:
        (mod_dir / "mcp_module.py").write_text(mcp_module_source)
    return mod_dir


def _tool_names(fresh_mcp) -> list[str]:
    return [t.name for t in fresh_mcp._tool_manager.list_tools()]


def test_enabled_module_tool_is_registered(db, tmp_path):
    from services.module_mcp_loader import register_module_mcp_tools

    _make_module(
        tmp_path,
        "mod-a",
        "def register(mcp):\n"
        "    @mcp.tool()\n"
        "    def mod_a_tool() -> str:\n"
        "        return 'ok'\n",
    )
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")

    fresh_mcp = FastMCP("test")
    with patch("services.module_mcp_loader._MODULE_MCP_ROOTS", [tmp_path]):
        result = register_module_mcp_tools(fresh_mcp)

    assert result == ["mod-a"]
    assert "mod_a_tool" in _tool_names(fresh_mcp)


def test_disabled_module_is_not_loaded(db, tmp_path):
    from services.module_mcp_loader import register_module_mcp_tools

    _make_module(
        tmp_path,
        "mod-a",
        "def register(mcp):\n"
        "    @mcp.tool()\n"
        "    def mod_a_tool() -> str:\n"
        "        return 'ok'\n",
    )

    fresh_mcp = FastMCP("test")
    with patch("services.module_mcp_loader._MODULE_MCP_ROOTS", [tmp_path]):
        result = register_module_mcp_tools(fresh_mcp)

    assert result == []
    assert "mod_a_tool" not in _tool_names(fresh_mcp)


def test_module_register_raising_is_skipped_and_host_tools_survive(db, tmp_path):
    from services.module_mcp_loader import register_module_mcp_tools

    fresh_mcp = FastMCP("test")

    @fresh_mcp.tool()
    def existing_tool_one() -> str:
        return "one"

    @fresh_mcp.tool()
    def existing_tool_two() -> str:
        return "two"

    _make_module(
        tmp_path,
        "mod-broken",
        "def register(mcp):\n"
        "    raise RuntimeError('boom')\n",
    )
    _enable_module(db, "mod-broken", "2024-01-01T00:00:00")

    with patch("services.module_mcp_loader._MODULE_MCP_ROOTS", [tmp_path]):
        result = register_module_mcp_tools(fresh_mcp)

    assert result == []
    names = _tool_names(fresh_mcp)
    assert "existing_tool_one" in names
    assert "existing_tool_two" in names


def test_module_without_mcp_module_is_ignored(db, tmp_path):
    from services.module_mcp_loader import register_module_mcp_tools

    _make_module(tmp_path, "mod-plain")
    _enable_module(db, "mod-plain", "2024-01-01T00:00:00")

    fresh_mcp = FastMCP("test")
    with patch("services.module_mcp_loader._MODULE_MCP_ROOTS", [tmp_path]):
        result = register_module_mcp_tools(fresh_mcp)

    assert result == []
    assert _tool_names(fresh_mcp) == []


def test_module_using_module_local_dataclass_annotation_registers(db, tmp_path):
    """register() decorates a tool whose param type is a dataclass defined in the
    same file, referenced via a string annotation (PEP 563). Resolving that
    forward reference requires the module to already be reachable through
    sys.modules under its own __module__ name at decoration time.
    """
    from services.module_mcp_loader import register_module_mcp_tools

    _make_module(
        tmp_path,
        "mod-typed",
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass\n"
        "class Payload:\n"
        "    value: str\n"
        "\n"
        "def register(mcp):\n"
        "    @mcp.tool()\n"
        "    def mod_typed_tool(payload: Payload) -> str:\n"
        "        return payload.value\n",
    )
    _enable_module(db, "mod-typed", "2024-01-01T00:00:00")

    fresh_mcp = FastMCP("test")
    with patch("services.module_mcp_loader._MODULE_MCP_ROOTS", [tmp_path]):
        result = register_module_mcp_tools(fresh_mcp)

    assert result == ["mod-typed"]
    assert "mod_typed_tool" in _tool_names(fresh_mcp)


def test_enabled_module_ids_is_public():
    from services.modules_discovery import enabled_module_ids

    assert callable(enabled_module_ids)
