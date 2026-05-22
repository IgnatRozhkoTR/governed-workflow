"""Tests for the manual review-action endpoints on the workspaces blueprint.

Covers ``POST /api/workspaces/<id>/review-issues/resolve-all`` and
``POST /api/workspaces/<id>/review-pipeline/start``.
"""
from datetime import datetime

import pytest

from testing_utils import add_comment, set_phase


def _add_review_issue(ws_id, text="finding", resolved=False):
    """Insert a scope='review' discussion. Returns its id."""
    from core.db import get_db
    db = get_db()
    now = datetime.now().isoformat()
    status = "resolved" if resolved else "open"
    resolved_at = now if resolved else None
    cursor = db.execute(
        "INSERT INTO discussions (workspace_id, scope, target, text, author, status, "
        "resolution, file_path, line_start, line_end, created_at, resolved_at) "
        "VALUES (?, 'review', ?, ?, 'reviewer', ?, 'open', 'src/main.py', 1, 1, ?, ?)",
        (ws_id, "src/main.py", text, status, now, resolved_at),
    )
    db.commit()
    issue_id = cursor.lastrowid
    db.close()
    return issue_id


def _get_discussion(disc_id):
    from core.db import get_db
    db = get_db()
    row = db.execute(
        "SELECT id, scope, status, resolution, resolved_at FROM discussions WHERE id = ?",
        (disc_id,),
    ).fetchone()
    db.close()
    return dict(row) if row else None


class TestResolveAllReviewIssues:
    def test_bulk_resolves_only_open_review_items(self, client, workspace):
        open_a = _add_review_issue(workspace["id"], "A")
        open_b = _add_review_issue(workspace["id"], "B")
        already_resolved = _add_review_issue(workspace["id"], "C", resolved=True)
        # A non-review scoped comment must NOT be touched.
        plan_comment = add_comment(workspace["id"], scope="plan", text="not a review")

        r = client.post(
            f"/api/workspaces/{workspace['id']}/review-issues/resolve-all",
            json={"resolution": "out_of_scope"},
        )
        assert r.status_code == 200, r.json
        assert r.json["resolved_count"] == 2

        for issue_id in (open_a, open_b):
            row = _get_discussion(issue_id)
            assert row["status"] == "resolved"
            assert row["resolution"] == "out_of_scope"
            assert row["resolved_at"] is not None

        unchanged = _get_discussion(already_resolved)
        assert unchanged["status"] == "resolved"
        # Pre-resolved row's resolution must stay 'open' (its previous value) — bulk only
        # touches currently-open items so we don't overwrite a deliberate resolution.
        assert unchanged["resolution"] == "open"

        plan_row = _get_discussion(plan_comment)
        assert plan_row["scope"] == "plan"
        assert plan_row["status"] == "open"
        assert plan_row["resolution"] is None

    def test_default_resolution_is_out_of_scope(self, client, workspace):
        issue_id = _add_review_issue(workspace["id"], "default")

        r = client.post(
            f"/api/workspaces/{workspace['id']}/review-issues/resolve-all",
            json={},
        )
        assert r.status_code == 200
        assert r.json["resolved_count"] == 1
        assert _get_discussion(issue_id)["resolution"] == "out_of_scope"

    def test_invalid_resolution_is_rejected(self, client, workspace):
        _add_review_issue(workspace["id"], "bad")
        r = client.post(
            f"/api/workspaces/{workspace['id']}/review-issues/resolve-all",
            json={"resolution": "wontfix"},
        )
        assert r.status_code == 400
        assert r.json["error"] == "invalid_resolution"

    def test_unknown_workspace_returns_404(self, client):
        r = client.post(
            "/api/workspaces/99999/review-issues/resolve-all",
            json={"resolution": "out_of_scope"},
        )
        assert r.status_code == 404

    def test_zero_open_issues_returns_zero(self, client, workspace):
        r = client.post(
            f"/api/workspaces/{workspace['id']}/review-issues/resolve-all",
            json={"resolution": "fixed"},
        )
        assert r.status_code == 200
        assert r.json["resolved_count"] == 0


class _FakeThread:
    """Stand-in for the daemon thread returned by start_in_background."""


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Replace start_in_background with a controllable stub.

    Returns the stub so tests can assert call args and flip its return value
    between a fake thread (started) and None (already running).
    """
    calls = []

    def stub(workspace_id, project_path, base_branch="main"):
        calls.append({
            "workspace_id": workspace_id,
            "project_path": str(project_path),
            "base_branch": base_branch,
        })
        return stub.return_value

    stub.return_value = _FakeThread()
    stub.calls = calls

    from services import review_pipeline_service
    monkeypatch.setattr(review_pipeline_service, "start_in_background", stub)
    return stub


class TestStartReviewPipeline:
    def test_starts_when_phase_is_4_0(self, client, workspace, stub_pipeline):
        set_phase(workspace["id"], "4.0")

        r = client.post(
            f"/api/workspaces/{workspace['id']}/review-pipeline/start",
            json={},
        )
        assert r.status_code == 202, r.json
        assert r.json["status"] == "started"
        assert len(stub_pipeline.calls) == 1
        call = stub_pipeline.calls[0]
        assert call["workspace_id"] == workspace["id"]
        # Default base branch comes from workspaces.source_branch (set to 'develop' by fixture).
        assert call["base_branch"] == "develop"

    def test_refuses_when_wrong_phase(self, client, workspace, stub_pipeline):
        # Default workspace fixture is at phase 0; no force given.
        r = client.post(
            f"/api/workspaces/{workspace['id']}/review-pipeline/start",
            json={},
        )
        assert r.status_code == 409
        assert r.json["error"] == "wrong_phase"
        assert r.json["phase"] == "0"
        assert stub_pipeline.calls == []

    def test_force_overrides_wrong_phase(self, client, workspace, stub_pipeline):
        r = client.post(
            f"/api/workspaces/{workspace['id']}/review-pipeline/start",
            json={"force": True},
        )
        assert r.status_code == 202
        assert len(stub_pipeline.calls) == 1

    def test_already_running_returns_409(self, client, workspace, stub_pipeline):
        set_phase(workspace["id"], "4.0")
        stub_pipeline.return_value = None  # simulate in-flight pipeline

        r = client.post(
            f"/api/workspaces/{workspace['id']}/review-pipeline/start",
            json={},
        )
        assert r.status_code == 409
        assert r.json["error"] == "already_running"

    def test_custom_base_branch_is_passed_through(self, client, workspace, stub_pipeline):
        set_phase(workspace["id"], "4.0")
        r = client.post(
            f"/api/workspaces/{workspace['id']}/review-pipeline/start",
            json={"base_branch": "main"},
        )
        assert r.status_code == 202
        assert stub_pipeline.calls[-1]["base_branch"] == "main"

    def test_unknown_workspace_returns_404(self, client, stub_pipeline):
        r = client.post(
            "/api/workspaces/99999/review-pipeline/start",
            json={},
        )
        assert r.status_code == 404
        assert stub_pipeline.calls == []
