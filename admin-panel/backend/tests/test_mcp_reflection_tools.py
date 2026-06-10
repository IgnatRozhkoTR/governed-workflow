"""Tests for workspace_get_reflection_context, workspace_list_proposals, and workspace_resolve_proposal MCP tools."""
import json


def _call_reflection(workspace, monkeypatch):
    monkeypatch.chdir(workspace["working_dir"])
    from mcp_server import workspace_get_reflection_context
    return workspace_get_reflection_context()


def _call_list(workspace, monkeypatch, **kwargs):
    monkeypatch.chdir(workspace["working_dir"])
    from mcp_server import workspace_list_proposals
    return workspace_list_proposals(**kwargs)


def _call_resolve(workspace, monkeypatch, proposal_id, status, **kwargs):
    monkeypatch.chdir(workspace["working_dir"])
    from mcp_server import workspace_resolve_proposal
    return workspace_resolve_proposal(proposal_id=proposal_id, status=status, **kwargs)


def _submit(workspace, monkeypatch, **kwargs):
    monkeypatch.chdir(workspace["working_dir"])
    from mcp_server import workspace_submit_proposal
    defaults = {
        "type": "rule_new",
        "implementation_kind": "manual",
        "title": "Test proposal",
        "body": "Some rationale.",
    }
    defaults.update(kwargs)
    result = workspace_submit_proposal(**defaults)
    assert "id" in result, f"submit failed: {result}"
    return result["id"]


# ---------------------------------------------------------------------------
# workspace_get_reflection_context
# ---------------------------------------------------------------------------

def test_get_reflection_context_returns_all_four_blobs(workspace, monkeypatch):
    result = _call_reflection(workspace, monkeypatch)

    assert "error" not in result
    assert "scope" in result
    assert "branch_diff" in result
    assert "review_findings" in result
    assert "transcript" in result
    assert result["workspace_id"] == workspace["id"]
    assert isinstance(result["transcript_truncated"], bool)


def test_get_reflection_context_returns_empty_transcript_when_session_missing(workspace, monkeypatch):
    result = _call_reflection(workspace, monkeypatch)

    assert "error" not in result
    assert result["transcript"] == []
    assert result["transcript_truncated"] is False


# ---------------------------------------------------------------------------
# workspace_list_proposals
# ---------------------------------------------------------------------------

def test_list_proposals_returns_all_when_no_filters(workspace, monkeypatch):
    _submit(workspace, monkeypatch, implementation_kind="auto")
    _submit(workspace, monkeypatch, implementation_kind="manual")

    result = _call_list(workspace, monkeypatch)

    assert "error" not in result
    assert len(result["proposals"]) == 2


def test_list_proposals_filters_by_implementation_kind(workspace, monkeypatch):
    _submit(workspace, monkeypatch, implementation_kind="auto", title="Auto")
    _submit(workspace, monkeypatch, implementation_kind="manual", title="Manual")

    result = _call_list(workspace, monkeypatch, implementation_kind="auto")

    assert "error" not in result
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["implementation_kind"] == "auto"


def test_list_proposals_filters_by_status(workspace, monkeypatch):
    proposal_id = _submit(workspace, monkeypatch)
    _call_resolve(workspace, monkeypatch, proposal_id=proposal_id, status="executed")

    result = _call_list(workspace, monkeypatch, status="executed")

    assert "error" not in result
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["status"] == "executed"


def test_list_proposals_returns_mcp_error_on_invalid_filter(workspace, monkeypatch):
    result = _call_list(workspace, monkeypatch, implementation_kind="robot")

    assert "error" in result
    assert result["errorCategory"] == "validation"
    assert result["isRetryable"] is False


# ---------------------------------------------------------------------------
# workspace_resolve_proposal
# ---------------------------------------------------------------------------

def test_resolve_proposal_sets_status_and_returns_row(workspace, monkeypatch):
    proposal_id = _submit(workspace, monkeypatch)

    result = _call_resolve(workspace, monkeypatch, proposal_id=proposal_id, status="executed")

    assert "error" not in result
    assert result["id"] == proposal_id
    assert result["status"] == "executed"
    assert result["executed_at"] is not None


def test_resolve_proposal_returns_not_found_when_id_missing(workspace, monkeypatch):
    result = _call_resolve(workspace, monkeypatch, proposal_id=999999, status="executed")

    assert "error" in result
    assert result["errorCategory"] == "not_found"
    assert result["isRetryable"] is False


def test_resolve_proposal_returns_not_found_when_proposal_belongs_to_other_workspace(
    workspace, second_workspace, monkeypatch
):
    from core.db import get_db
    from services.proposal_service import create_proposal

    db = get_db()
    try:
        proposal_id = create_proposal(
            db,
            workspace_id=workspace["id"],
            project_id=workspace["project_id"],
            type="rule_new",
            implementation_kind="manual",
            title="Workspace 1 proposal",
            body="body",
        )
        db.commit()
    finally:
        db.close()

    # _detect_workspace picks second_workspace (higher id) from shared working_dir,
    # so the proposal owned by workspace 1 is inaccessible from that context.
    monkeypatch.chdir(second_workspace["working_dir"])
    from mcp_server import workspace_resolve_proposal
    result = workspace_resolve_proposal(proposal_id=proposal_id, status="executed")

    assert "error" in result
    assert result["errorCategory"] == "not_found"


def test_resolve_proposal_returns_validation_error_when_result_json_unparseable(workspace, monkeypatch):
    proposal_id = _submit(workspace, monkeypatch)

    result = _call_resolve(
        workspace, monkeypatch,
        proposal_id=proposal_id,
        status="executed",
        result_json="not-valid-json{{{",
    )

    assert "error" in result
    assert result["errorCategory"] == "validation"
    assert result["isRetryable"] is False


def test_resolve_proposal_is_idempotent_for_same_terminal_status(workspace, monkeypatch):
    proposal_id = _submit(workspace, monkeypatch)
    _call_resolve(workspace, monkeypatch, proposal_id=proposal_id, status="executed")

    result = _call_resolve(workspace, monkeypatch, proposal_id=proposal_id, status="executed")

    assert "error" not in result
    assert result["status"] == "executed"


def test_resolve_proposal_returns_business_error_when_changing_terminal_status(workspace, monkeypatch):
    proposal_id = _submit(workspace, monkeypatch)
    _call_resolve(workspace, monkeypatch, proposal_id=proposal_id, status="executed")

    result = _call_resolve(workspace, monkeypatch, proposal_id=proposal_id, status="rejected")

    assert "error" in result
    assert result["errorCategory"] == "business"
    assert result["isRetryable"] is False
    assert result["code"] == "already_resolved"
