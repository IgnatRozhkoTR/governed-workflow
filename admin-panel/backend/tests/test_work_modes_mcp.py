"""Tests for work-mode MCP tools (sub-phase 3.6)."""
import pytest

from core.db import get_db
from mcp_tools.work_modes import (
    work_mode_create,
    work_mode_list,
    work_mode_get,
    work_mode_update,
    work_mode_assign,
    work_mode_apply,
)


@pytest.fixture(autouse=True)
def _require_db(clean_db):
    yield


@pytest.fixture
def user_mode():
    db = get_db()
    try:
        from services import work_mode_service
        mode = work_mode_service.create(
            db,
            name="mcp-test-mode",
            description="MCP test",
            phases=[{"phase_id": "1.1", "enabled": True, "position": 0}],
        )
    finally:
        db.close()
    return mode


# ── work_mode_create ──────────────────────────────────────────────────────────

def test_work_mode_create_happy():
    result = work_mode_create(
        name="fast-track",
        description="Skip non-essential phases",
        phases=[{"phase_id": "1.1", "enabled": False, "position": 0}],
    )

    assert "error" not in result
    assert result["name"] == "fast-track"
    assert result["origin"] == "user"
    assert isinstance(result["id"], int)


def test_work_mode_create_name_collision_envelope(user_mode):
    result = work_mode_create(name="mcp-test-mode")

    assert "error" in result
    assert result["errorCategory"] == "business"
    assert result["isRetryable"] is False


def test_work_mode_create_invalid_phases_envelope():
    result = work_mode_create(
        name="bad-phases",
        phases=[{"no_phase_id": True}],
    )

    assert "error" in result
    assert result["errorCategory"] == "validation"


# ── work_mode_list ────────────────────────────────────────────────────────────

def test_work_mode_list_returns_all_modes():
    result = work_mode_list()

    assert isinstance(result, list)
    names = {m["name"] for m in result if isinstance(m, dict) and "name" in m}
    assert "basic" in names


# ── work_mode_get ─────────────────────────────────────────────────────────────

def test_work_mode_get_returns_mode(user_mode):
    result = work_mode_get(mode_id=user_mode["id"])

    assert "error" not in result
    assert result["id"] == user_mode["id"]
    assert result["name"] == user_mode["name"]


def test_work_mode_get_not_found_envelope():
    result = work_mode_get(mode_id=999999)

    assert "error" in result
    assert result["errorCategory"] == "not_found"
    assert result["isRetryable"] is False


# ── work_mode_update ──────────────────────────────────────────────────────────

def test_work_mode_update_invalid_phases_envelope(user_mode):
    result = work_mode_update(
        mode_id=user_mode["id"],
        phases=[{"bad": "data"}],
    )

    assert "error" in result
    assert result["errorCategory"] == "validation"


def test_work_mode_update_system_immutable_envelope():
    modes = work_mode_list()
    basic = next(m for m in modes if isinstance(m, dict) and m.get("name") == "basic")

    result = work_mode_update(mode_id=basic["id"], description="hacked")

    assert "error" in result
    assert result["errorCategory"] == "business"
    assert result["isRetryable"] is False


# ── work_mode_assign ──────────────────────────────────────────────────────────

def test_work_mode_assign_returns_workspace_with_new_mode_id(workspace):
    modes = work_mode_list()
    basic = next(m for m in modes if isinstance(m, dict) and m.get("name") == "basic")

    result = work_mode_assign(workspace_id=workspace["id"], mode_id=basic["id"])

    assert "error" not in result
    assert result["workspace_id"] == workspace["id"]
    assert result["mode_id"] == basic["id"]

    db = get_db()
    try:
        row = db.execute(
            "SELECT phase, work_mode_id FROM workspaces WHERE id = ?", (workspace["id"],)
        ).fetchone()
        assert row["work_mode_id"] == basic["id"]
        assert row["phase"] == workspace["phase"]
    finally:
        db.close()


# ── work_mode_apply ───────────────────────────────────────────────────────────

def test_work_mode_apply_returns_effective_phase_list(workspace):
    result = work_mode_apply(workspace_id=workspace["id"])

    assert "error" not in result
    assert "effective_phases" in result
    assert isinstance(result["effective_phases"], list)
    assert len(result["effective_phases"]) > 0
