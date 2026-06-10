"""Tests for comment CRUD, resolve, and list routes."""
from testing_utils import add_comment

BASE = "/api/ws/test-project/feature/test/comments"


def test_add_comment(client, workspace):
    r = client.post(BASE, json={"scope": "review", "text": "Fix this"})
    assert r.status_code == 200
    assert r.json["ok"]
    assert r.json["id"]


def test_add_comment_missing_fields(client, workspace):
    r = client.post(BASE, json={"scope": "review"})
    assert r.status_code == 400

    r = client.post(BASE, json={"text": "Some text"})
    assert r.status_code == 400


def test_add_comment_with_file_location(client, workspace):
    r = client.post(BASE, json={
        "scope": "review",
        "text": "Check this line",
        "file_path": "src/main.py",
        "line_start": 5,
        "line_end": 10,
        "line_hash": "abc123",
    })
    assert r.status_code == 200
    assert r.json["ok"]

    comment_id = r.json["id"]
    r = client.get(BASE)
    comments = r.json["comments"]
    comment = next(c for c in comments if c["id"] == comment_id)
    assert comment["file_path"] == "src/main.py"
    assert comment["line_start"] == 5
    assert comment["line_end"] == 10
    assert comment["line_hash"] == "abc123"


def test_list_comments(client, workspace):
    add_comment(workspace["id"], scope="review", text="First")
    add_comment(workspace["id"], scope="review", text="Second")

    r = client.get(BASE)
    assert r.status_code == 200
    assert len(r.json["comments"]) == 2


def test_list_comments_filter_scope(client, workspace):
    add_comment(workspace["id"], scope="review", text="Review comment")
    add_comment(workspace["id"], scope="phase", text="Phase comment")

    r = client.get(BASE, query_string={"scope": "review"})
    assert r.status_code == 200
    comments = r.json["comments"]
    assert len(comments) == 1
    assert comments[0]["scope"] == "review"


def test_list_comments_filter_resolved(client, workspace):
    resolved_id = add_comment(workspace["id"], scope="review", text="Resolved comment")
    add_comment(workspace["id"], scope="review", text="Open comment")

    client.put(f"{BASE}/{resolved_id}/resolve", json={"resolved": True})

    r = client.get(BASE, query_string={"resolved": "false"})
    assert r.status_code == 200
    comments = r.json["comments"]
    assert len(comments) == 1
    assert comments[0]["resolved"] is False


def test_resolve_comment(client, workspace):
    comment_id = add_comment(workspace["id"], scope="review", text="Needs fix")

    r = client.put(f"{BASE}/{comment_id}/resolve", json={"resolved": True})
    assert r.status_code == 200
    assert r.json["ok"]

    r = client.get(BASE)
    comment = next(c for c in r.json["comments"] if c["id"] == comment_id)
    assert comment["resolved"] is True
    assert comment["resolved_at"] is not None


def test_unresolve_comment(client, workspace):
    comment_id = add_comment(workspace["id"], scope="review", text="Needs fix")

    client.put(f"{BASE}/{comment_id}/resolve", json={"resolved": True})
    r = client.put(f"{BASE}/{comment_id}/resolve", json={"resolved": False})
    assert r.status_code == 200
    assert r.json["ok"]

    r = client.get(BASE)
    comment = next(c for c in r.json["comments"] if c["id"] == comment_id)
    assert comment["resolved"] is False
    assert comment["resolved_at"] is None


def test_resolve_comment_not_found(client, workspace):
    r = client.put(f"{BASE}/99999/resolve", json={"resolved": True})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Batch resolve — workspace_resolve_comment (MCP tool, service layer)
# ---------------------------------------------------------------------------

def _add_review_discussion(ws_id, text="finding"):
    """Insert a scope='review' discussion row directly."""
    from core.db import get_db
    from datetime import datetime
    db = get_db()
    cursor = db.execute(
        "INSERT INTO discussions (workspace_id, scope, target, text, author, status, "
        "resolution, file_path, line_start, line_end, created_at) "
        "VALUES (?, 'review', 'src/main.py', ?, 'reviewer', 'open', 'open', "
        "'src/main.py', 1, 1, ?)",
        (ws_id, text, datetime.now().isoformat()),
    )
    db.commit()
    issue_id = cursor.lastrowid
    db.close()
    return issue_id


class TestBatchResolveComments:
    def test_batch_resolves_multiple_comments(self, workspace, monkeypatch):
        cid1 = add_comment(workspace["id"], scope="plan", text="C1")
        cid2 = add_comment(workspace["id"], scope="plan", text="C2")
        cid3 = add_comment(workspace["id"], scope="plan", text="C3")
        monkeypatch.chdir(workspace["working_dir"])

        from mcp_server import workspace_resolve_comment
        result = workspace_resolve_comment(comment_ids=[cid1, cid2, cid3])

        assert result["count"] == 3
        assert set(result["resolved"]) == {cid1, cid2, cid3}
        assert result["not_found"] == []
        assert result["already_resolved"] == []

    def test_batch_mixed_valid_not_found_already_resolved(self, workspace, monkeypatch):
        cid_open = add_comment(workspace["id"], scope="plan", text="Open")
        cid_missing = 999999

        from core.db import get_db
        from datetime import datetime
        db = get_db()
        cursor = db.execute(
            "INSERT INTO discussions (workspace_id, scope, target, text, author, status, created_at) "
            "VALUES (?, 'plan', 'x', 'Already resolved', 'user', 'resolved', ?)",
            (workspace["id"], datetime.now().isoformat()),
        )
        db.commit()
        cid_resolved = cursor.lastrowid
        db.close()

        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_comment
        result = workspace_resolve_comment(comment_ids=[cid_open, cid_missing, cid_resolved])

        assert result["count"] == 1
        assert cid_open in result["resolved"]
        assert cid_missing in result["not_found"]
        assert cid_resolved in result["already_resolved"]

    def test_batch_review_scope_goes_to_not_found(self, workspace, monkeypatch):
        cid_review = _add_review_discussion(workspace["id"])
        cid_normal = add_comment(workspace["id"], scope="plan", text="Normal")
        monkeypatch.chdir(workspace["working_dir"])

        from mcp_server import workspace_resolve_comment
        result = workspace_resolve_comment(comment_ids=[cid_review, cid_normal])

        assert result["count"] == 1
        assert cid_normal in result["resolved"]
        assert cid_review in result["not_found"]

    def test_batch_empty_list_returns_validation_error(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])

        from mcp_server import workspace_resolve_comment
        result = workspace_resolve_comment(comment_ids=[])

        assert "error" in result
        assert result["errorCategory"] == "validation"

    def test_batch_single_element_resolves_comment(self, workspace, monkeypatch):
        cid = add_comment(workspace["id"], scope="comment", text="Feedback")
        monkeypatch.chdir(workspace["working_dir"])

        from mcp_server import workspace_resolve_comment, workspace_get_comments
        result = workspace_resolve_comment(comment_ids=[cid])

        assert result["count"] == 1
        assert cid in result["resolved"]
        unresolved = workspace_get_comments(unresolved_only=True)
        assert not any(c["id"] == cid for c in unresolved)

    def test_batch_foreign_workspace_id_goes_to_not_found(self, workspace, second_workspace):
        foreign_cid = add_comment(second_workspace["id"], scope="plan", text="Foreign")

        from services.comment_service import resolve_comments_batch
        from core.db import get_db
        db = get_db()
        try:
            result = resolve_comments_batch(db, workspace["id"], [foreign_cid])
        finally:
            db.close()

        assert result["count"] == 0
        assert foreign_cid in result["not_found"]


class TestBatchResolveReviewIssues:
    def test_batch_resolves_several_issues(self, workspace, monkeypatch):
        iid1 = _add_review_discussion(workspace["id"], "Issue A")
        iid2 = _add_review_discussion(workspace["id"], "Issue B")
        iid3 = _add_review_discussion(workspace["id"], "Issue C")
        monkeypatch.chdir(workspace["working_dir"])

        from mcp_server import workspace_resolve_review_issue
        result = workspace_resolve_review_issue(issue_ids=[iid1, iid2, iid3], resolution="fixed")

        assert result["count"] == 3
        assert set(result["resolved"]) == {iid1, iid2, iid3}
        assert result["not_found"] == []
        assert result["already_resolved"] == []

    def test_batch_mixed_valid_not_found_already_resolved(self, workspace, monkeypatch):
        iid_open = _add_review_discussion(workspace["id"], "Open issue")
        iid_missing = 888888

        from core.db import get_db
        iid_fixed = _add_review_discussion(workspace["id"], "Already fixed")
        db2 = get_db()
        db2.execute("UPDATE discussions SET resolution = 'fixed' WHERE id = ?", (iid_fixed,))
        db2.commit()
        db2.close()

        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_review_issue
        result = workspace_resolve_review_issue(
            issue_ids=[iid_open, iid_missing, iid_fixed], resolution="fixed"
        )

        assert result["count"] == 1
        assert iid_open in result["resolved"]
        assert iid_missing in result["not_found"]
        assert iid_fixed in result["already_resolved"]

    def test_batch_false_positive_resolution(self, workspace, monkeypatch):
        iid1 = _add_review_discussion(workspace["id"], "FP issue 1")
        iid2 = _add_review_discussion(workspace["id"], "FP issue 2")
        monkeypatch.chdir(workspace["working_dir"])

        from mcp_server import workspace_resolve_review_issue
        result = workspace_resolve_review_issue(issue_ids=[iid1, iid2], resolution="false_positive")

        assert result["count"] == 2
        assert set(result["resolved"]) == {iid1, iid2}

        from core.db import get_db
        db = get_db()
        row = db.execute("SELECT resolution FROM discussions WHERE id = ?", (iid1,)).fetchone()
        db.close()
        assert row["resolution"] == "false_positive"

    def test_batch_fixed_resolution(self, workspace, monkeypatch):
        iid = _add_review_discussion(workspace["id"], "Fixed issue")
        monkeypatch.chdir(workspace["working_dir"])

        from mcp_server import workspace_resolve_review_issue
        result = workspace_resolve_review_issue(issue_ids=[iid], resolution="fixed")

        assert result["count"] == 1

        from core.db import get_db
        db = get_db()
        row = db.execute("SELECT resolution FROM discussions WHERE id = ?", (iid,)).fetchone()
        db.close()
        assert row["resolution"] == "fixed"

    def test_batch_empty_list_returns_validation_error(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])

        from mcp_server import workspace_resolve_review_issue
        result = workspace_resolve_review_issue(issue_ids=[], resolution="fixed")

        assert "error" in result
        assert result["errorCategory"] == "validation"

    def test_batch_foreign_workspace_id_goes_to_not_found(self, workspace, second_workspace):
        foreign_iid = _add_review_discussion(second_workspace["id"], "Foreign issue")

        from services.comment_service import resolve_review_issues_batch
        from core.db import get_db
        db = get_db()
        try:
            result = resolve_review_issues_batch(db, workspace["id"], [foreign_iid], "fixed")
        finally:
            db.close()

        assert result["count"] == 0
        assert foreign_iid in result["not_found"]

    def test_batch_single_element_resolves_issue(self, workspace, monkeypatch):
        iid = _add_review_discussion(workspace["id"], "Single issue")
        monkeypatch.chdir(workspace["working_dir"])

        from mcp_server import workspace_resolve_review_issue, workspace_get_review_issues
        result = workspace_resolve_review_issue(issue_ids=[iid], resolution="out_of_scope")

        assert result["count"] == 1
        issues = workspace_get_review_issues(status="out_of_scope")
        assert any(i["id"] == iid for i in issues)
