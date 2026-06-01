"""Tests for the workspace_submit_proposal MCP tool."""
import json

import pytest


def _call(workspace, monkeypatch, **kwargs):
    """Call workspace_submit_proposal with workspace context and sensible defaults."""
    monkeypatch.chdir(workspace["working_dir"])
    from mcp_server import workspace_submit_proposal

    defaults = {
        "type": "rule_new",
        "implementation_kind": "manual",
        "title": "Test proposal",
        "body": "Some rationale.",
    }
    defaults.update(kwargs)
    return workspace_submit_proposal(**defaults)


def test_submit_proposal_returns_id_and_status_when_success(workspace, monkeypatch):
    result = _call(workspace, monkeypatch)

    assert "error" not in result
    assert isinstance(result["id"], int)
    assert result["id"] > 0
    assert result["status"] == "proposed"


def test_submit_proposal_inserts_row_with_correct_fields(workspace, monkeypatch):
    result = _call(
        workspace, monkeypatch,
        type="memory_write",
        implementation_kind="auto",
        title="Remember the thing",
        body="Detailed rationale.",
        reason="Session abc123",
    )

    from core.db import get_db
    db = get_db()
    try:
        row = db.execute(
            "SELECT type, implementation_kind, title, body, reason, status "
            "FROM proposals WHERE id = ?",
            (result["id"],),
        ).fetchone()
    finally:
        db.close()

    assert row is not None
    assert row["type"] == "memory_write"
    assert row["implementation_kind"] == "auto"
    assert row["title"] == "Remember the thing"
    assert row["body"] == "Detailed rationale."
    assert row["reason"] == "Session abc123"
    assert row["status"] == "proposed"


def test_submit_proposal_stores_origin_reflection(workspace, monkeypatch):
    result = _call(workspace, monkeypatch)

    from core.db import get_db
    db = get_db()
    try:
        row = db.execute(
            "SELECT origin FROM proposals WHERE id = ?", (result["id"],)
        ).fetchone()
    finally:
        db.close()

    assert row is not None
    assert row["origin"] == "reflection"


def test_submit_proposal_returns_mcp_error_when_type_invalid(workspace, monkeypatch):
    result = _call(workspace, monkeypatch, type="delete_everything")

    assert "error" in result
    assert result["errorCategory"] == "validation"
    assert result["isRetryable"] is False


def test_submit_proposal_returns_mcp_error_when_implementation_kind_invalid(workspace, monkeypatch):
    result = _call(workspace, monkeypatch, implementation_kind="robot")

    assert "error" in result
    assert result["errorCategory"] == "validation"
    assert result["isRetryable"] is False


def test_submit_proposal_returns_mcp_error_when_payload_json_unparseable(workspace, monkeypatch):
    result = _call(workspace, monkeypatch, payload_json="not-valid-json{{{")

    assert "error" in result
    assert result["errorCategory"] == "validation"
    assert result["isRetryable"] is False
    assert "payload_json" in result["error"]


def test_submit_proposal_stores_valid_payload_json(workspace, monkeypatch):
    payload = json.dumps({"key": "value", "num": 42})
    result = _call(workspace, monkeypatch, payload_json=payload)

    from core.db import get_db
    db = get_db()
    try:
        row = db.execute(
            "SELECT payload_json FROM proposals WHERE id = ?", (result["id"],)
        ).fetchone()
    finally:
        db.close()

    assert row is not None
    assert json.loads(row["payload_json"]) == {"key": "value", "num": 42}


def test_submit_proposal_returns_error_when_no_workspace(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from mcp_server import workspace_submit_proposal

    result = workspace_submit_proposal(
        type="rule_new",
        implementation_kind="manual",
        title="No workspace",
        body="Body",
    )

    assert "error" in result
