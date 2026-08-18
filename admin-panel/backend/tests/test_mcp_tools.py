"""Tests for MCP tool functions in mcp_server.py.

Import mcp_server functions inside test functions — mcp_server calls init_db() on import,
so the import must happen after setup_db (session autouse) patches DB_PATH.
"""
import json
import os
from pathlib import Path

from testing_utils import (
    set_phase, add_progress, add_research, add_comment,
    add_criterion, make_plan_json, _git
)


class TestGetState:
    def test_no_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_get_state
        result = workspace_get_state()
        assert "error" in result

    def test_basic_state(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_state
        result = workspace_get_state()
        assert result["phase"] == "0"
        assert result["scope"] == {}

    def test_full_state_with_data(self, workspace, monkeypatch):
        add_research(workspace["id"])
        add_comment(workspace["id"])
        add_progress(workspace["id"], "1.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_state
        result = workspace_get_state()
        assert len(result["research_summary"]) == 1
        assert "1.0" in result["progress_summary"]

    def test_state_includes_branch_and_working_dir(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_state
        result = workspace_get_state()
        assert result["branch"] == workspace["branch"]
        assert result["working_dir"] == workspace["working_dir"]

    def test_state_no_gate_nonce(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_state
        result = workspace_get_state()
        assert "gate_nonce" not in result

    def test_state_empty_collections(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_state
        result = workspace_get_state()
        assert result["research_summary"] == []
        assert result["unresolved_comments_count"] == 0
        assert result["review_issues_summary"] == {}
        assert result["criteria_summary"] == {}
        assert result["previous_sessions_count"] == 0


class TestAdvance:
    def test_advance_from_0(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_advance
        result = workspace_advance()
        assert result["phase"] == "1.0"

    def test_advance_blocked(self, workspace, monkeypatch):
        set_phase(workspace["id"], "1.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_advance
        result = workspace_advance()
        assert "blocked" in result.get("status", "") or "message" in result

    def test_advance_at_user_gate(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.1")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_advance
        result = workspace_advance()
        assert "error" in result

    def test_advance_no_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_advance
        result = workspace_advance()
        assert "error" in result


class TestSetPlanScope:
    """Scope is now embedded in the plan and set via workspace_set_plan."""

    def test_set_plan_persists_per_item_scope(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_set_plan, workspace_get_state
        plan = {
            "systemDiagram": "",
            "execution": [
                {"id": "3.1", "name": "P1", "scope": {"must": ["src/"], "may": ["tests/"]}, "tasks": []}
            ],
        }
        result = workspace_set_plan(plan=plan)
        assert result["ok"] is True

        state = workspace_get_state()
        assert state["scope"] == {"3.1": {"must": ["src/"], "may": ["tests/"]}}

    def test_set_plan_rejects_item_without_scope(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_set_plan
        plan = {"systemDiagram": "", "execution": [{"id": "3.1", "name": "P1", "tasks": []}]}
        result = workspace_set_plan(plan=plan)
        assert "error" in result

    def test_get_scope_reconstructs_phase_keyed_map(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_set_plan, workspace_get_state
        plan = {
            "systemDiagram": "",
            "execution": [
                {"id": "3.1", "name": "P1", "scope": {"must": ["a/"], "may": []}, "tasks": []},
                {"id": "3.2", "name": "P2", "scope": {"must": ["b/"], "may": ["c/"]}, "tasks": []},
            ],
        }
        workspace_set_plan(plan=plan)

        state = workspace_get_state()
        assert state["scope"] == {
            "3.1": {"must": ["a/"], "may": []},
            "3.2": {"must": ["b/"], "may": ["c/"]},
        }


class TestSetPlan:
    def test_set_plan_success(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_set_plan
        plan = {
            "systemDiagram": "",
            "execution": [
                {
                    "id": "3.1",
                    "name": "Phase 1",
                    "scope": {"must": ["src/"]},
                    "tasks": [],
                }
            ],
        }
        result = workspace_set_plan(plan=plan)
        assert result["ok"]

    def test_set_plan_blocked_early(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_set_plan
        result = workspace_set_plan(plan={})
        assert "error" in result

    def test_set_plan_no_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_set_plan
        result = workspace_set_plan(plan={})
        assert "error" in result

    def test_set_plan_persisted(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_set_plan, workspace_get_plan
        plan = {"systemDiagram": "graph LR", "execution": []}
        workspace_set_plan(plan=plan)
        full_plan = workspace_get_plan()
        assert full_plan["systemDiagram"] == "graph LR"


class TestDiscussions:
    def test_post_discussion(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_post_discussion
        result = workspace_post_discussion(topic="Should we use X?")
        assert result["ok"]
        assert result["discussion_id"]

    def test_post_discussion_no_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_post_discussion
        result = workspace_post_discussion(topic="Test")
        assert "error" in result

    def test_post_discussion_no_context(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_post_discussion
        result = workspace_post_discussion(topic="Async vs sync approach")
        assert result["ok"]
        assert result["discussion_id"]

    def test_post_discussion_visible_in_state(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_post_discussion, workspace_get_state
        workspace_post_discussion(topic="Architecture decision")
        state = workspace_get_state()
        assert len(state["discussions"]) == 1
        assert state["discussions"][0]["text"] == "Architecture decision"


class TestResearch:
    def test_save_research(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_research
        findings = [
            {
                "summary": "Found X",
                "details": "Details",
                "proof": {
                    "type": "web",
                    "url": "http://example.com",
                    "title": "Title",
                    "quote": "Quote",
                },
            }
        ]
        result = workspace_save_research(topic="Auth flow", findings=findings)
        assert result["ok"]
        assert result["research_id"]

    def test_save_research_empty_findings(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_research
        result = workspace_save_research(topic="Empty", findings=[])
        assert "error" in result

    def test_save_research_no_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_save_research
        result = workspace_save_research(topic="Test", findings=[{"summary": "x"}])
        assert "error" in result

    def test_save_research_with_code_proof_enrichment(self, workspace, monkeypatch):
        Path(workspace["working_dir"]).joinpath("src").mkdir(exist_ok=True)
        Path(workspace["working_dir"]).joinpath("src/service.py").write_text(
            "line1\nline2\nline3\nline4\nline5\n"
        )
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_research
        findings = [
            {
                "summary": "Found pattern",
                "proof": {
                    "type": "code",
                    "file": "src/service.py",
                    "line_start": 1,
                    "line_end": 5,
                    "snippet_start": 2,
                    "snippet_end": 4,
                },
            }
        ]
        result = workspace_save_research(topic="Code analysis", findings=findings)
        assert result["ok"]

    def test_list_research(self, workspace, monkeypatch):
        add_research(workspace["id"], topic="Topic 1")
        add_research(workspace["id"], topic="Topic 2")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_list_research
        result = workspace_list_research()
        assert len(result) == 2

    def test_list_research_empty(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_list_research
        result = workspace_list_research()
        assert result == []

    def test_get_research_by_ids(self, workspace, monkeypatch):
        rid = add_research(workspace["id"])
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_research
        result = workspace_get_research(ids=[rid])
        assert len(result) == 1
        assert result[0]["id"] == rid

    def test_get_research_empty_ids(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_research
        result = workspace_get_research(ids=[])
        assert result == []

    def test_get_research_unknown_id(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_research
        result = workspace_get_research(ids=[9999])
        assert result == []

    def test_prove_research(self, workspace, monkeypatch):
        rid = add_research(workspace["id"])
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_prove_research
        result = workspace_prove_research(id=rid, proven=True, notes="Verified")
        assert result["ok"]
        assert result["proven"] is True

    def test_prove_research_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_prove_research
        result = workspace_prove_research(id=9999, proven=True)
        assert "error" in result

    def test_prove_research_rejected(self, workspace, monkeypatch):
        rid = add_research(workspace["id"])
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_prove_research
        result = workspace_prove_research(id=rid, proven=False, notes="Could not verify")
        assert result["ok"]
        assert result["proven"] is False

    def test_save_research_with_summary(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_research, workspace_list_research, workspace_get_research
        findings = [
            {
                "summary": "Found pattern",
                "proof": {"type": "web", "url": "http://example.com", "title": "T", "quote": "Q"},
            }
        ]
        result = workspace_save_research(
            topic="Summary test", findings=findings, summary="Overall this research found a pattern."
        )
        assert result["ok"]
        rid = result["research_id"]

        listed = workspace_list_research()
        entry = next(e for e in listed if e["id"] == rid)
        assert entry["summary"] == "Overall this research found a pattern."

        full = workspace_get_research(ids=[rid])
        assert full[0]["summary"] == "Overall this research found a pattern."

    def test_save_research_without_summary(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_research, workspace_list_research, workspace_get_research
        findings = [
            {
                "summary": "Found something",
                "proof": {"type": "web", "url": "http://example.com", "title": "T", "quote": "Q"},
            }
        ]
        result = workspace_save_research(topic="No summary test", findings=findings)
        assert result["ok"]
        rid = result["research_id"]

        listed = workspace_list_research()
        entry = next(e for e in listed if e["id"] == rid)
        assert entry["summary"] is None

        full = workspace_get_research(ids=[rid])
        assert full[0]["summary"] is None

    def test_save_research_finding_not_dict_returns_validation_error(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_research
        result = workspace_save_research(topic="Bad shape", findings=["not a dict"])
        assert "error" in result
        assert result["errorCategory"] == "validation"
        assert result["isRetryable"] is False

    def test_save_research_proof_missing_file_returns_validation_error(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_research
        findings = [{
            "summary": "Found something",
            "proof": {"type": "code", "line_start": 1, "line_end": 5},
        }]
        result = workspace_save_research(topic="Missing file", findings=findings)
        assert "error" in result
        assert result["errorCategory"] == "validation"
        assert "file" in result["error"]

    def test_save_research_valid_web_proof_still_works(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_save_research
        findings = [{
            "summary": "Found something",
            "proof": {"type": "web", "url": "http://example.com", "title": "T", "quote": "Q"},
        }]
        result = workspace_save_research(topic="Web proof", findings=findings)
        assert result["ok"] is True

    def test_save_research_normalizes_paths(self, workspace, monkeypatch, tmp_path):
        # Simulate agent running from a subdirectory
        subdir = Path(workspace["working_dir"]) / "src"
        subdir.mkdir(exist_ok=True)
        (subdir / "main.py").write_text("x = 1\n" * 20)
        monkeypatch.chdir(str(subdir))

        from mcp_server import workspace_save_research
        result = workspace_save_research(
            topic="Path test",
            findings=[{
                "summary": "Found something",
                "proof": {
                    "type": "code",
                    "file": "main.py",  # relative to cwd (src/), not working_dir
                    "line_start": 1,
                    "line_end": 5,
                }
            }]
        )
        assert result["ok"]

        # Verify the stored path is relative to working_dir, not cwd
        from mcp_server import workspace_get_research
        entries = workspace_get_research(ids=[result["research_id"]])
        assert entries[0]["findings"][0]["proof"]["file"] == "src/main.py"


class TestComments:
    def test_get_comments_empty(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_comments
        result = workspace_get_comments()
        assert result == []

    def test_get_comments_filtered(self, workspace, monkeypatch):
        add_comment(workspace["id"], scope="review", text="Review comment")
        add_comment(workspace["id"], scope="phase", text="Phase comment")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_comments
        result = workspace_get_comments(scope="review", unresolved_only=False)
        assert len(result) == 1
        assert result[0]["scope"] == "review"

    def test_get_comments_unresolved_only_default(self, workspace, monkeypatch):
        cid = add_comment(workspace["id"])
        from core.db import get_db
        db = get_db()
        db.execute("UPDATE discussions SET status = 'resolved' WHERE id = ?", (cid,))
        db.commit()
        db.close()
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_comments
        result = workspace_get_comments()
        assert result == []

    def test_resolve_comment(self, workspace, monkeypatch):
        cid = add_comment(workspace["id"])
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_comment
        result = workspace_resolve_comment(comment_ids=[cid])
        assert result["count"] == 1
        assert cid in result["resolved"]

    def test_resolve_comment_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_comment
        result = workspace_resolve_comment(comment_ids=[9999])
        assert result["count"] == 0
        assert 9999 in result["not_found"]

    def test_resolve_comment_marks_resolved(self, workspace, monkeypatch):
        cid = add_comment(workspace["id"])
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_comment, workspace_get_comments
        workspace_resolve_comment(comment_ids=[cid])
        result = workspace_get_comments(unresolved_only=True)
        assert result == []


class TestReviewIssues:
    def test_submit_review_issue(self, workspace, monkeypatch):
        Path(workspace["working_dir"]).joinpath("src").mkdir(exist_ok=True)
        Path(workspace["working_dir"]).joinpath("src/main.py").write_text(
            "def main():\n    pass\n    return\n"
        )
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_submit_review_issue
        result = workspace_submit_review_issue(
            file_path="src/main.py",
            line_start=1,
            line_end=3,
            severity="critical",
            description="Dead code",
        )
        assert result["ok"]

    def test_submit_issue_file_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_submit_review_issue
        result = workspace_submit_review_issue(
            file_path="nonexistent.py",
            line_start=1,
            line_end=1,
            severity="major",
            description="Test",
        )
        assert "error" in result

    def test_submit_issue_invalid_severity(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_submit_review_issue
        result = workspace_submit_review_issue(
            file_path="any.py",
            line_start=1,
            line_end=1,
            severity="minor",
            description="Test",
        )
        assert "error" in result

    def test_submit_issue_no_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_submit_review_issue
        result = workspace_submit_review_issue(
            file_path="file.py",
            line_start=1,
            line_end=1,
            severity="critical",
            description="Test",
        )
        assert "error" in result

    def test_get_review_issues(self, workspace, monkeypatch):
        add_comment(
            workspace["id"], scope="review", text="Test issue", resolution="open",
            file_path="src/main.py", line_start=1, line_end=3
        )
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_review_issues
        result = workspace_get_review_issues()
        assert len(result) == 1
        issue = result[0]
        assert "description" in issue
        assert "resolution" in issue
        assert "author" in issue
        assert "resolved" in issue

    def test_get_review_issues_filtered(self, workspace, monkeypatch):
        add_comment(
            workspace["id"], scope="review", text="Open issue", resolution="open",
            file_path="src/main.py", line_start=1, line_end=3
        )
        add_comment(
            workspace["id"], scope="review", text="Fixed issue", resolution="fixed",
            file_path="src/main.py", line_start=5, line_end=7
        )
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_review_issues
        result = workspace_get_review_issues(status="open")
        assert len(result) == 1
        result2 = workspace_get_review_issues(status="fixed")
        assert len(result2) == 1
        result3 = workspace_get_review_issues(status="out_of_scope")
        assert len(result3) == 0

    def test_resolve_review_issue(self, workspace, monkeypatch):
        iid = add_comment(workspace["id"], scope="review", text="Test issue", resolution="open")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_review_issue
        result = workspace_resolve_review_issue(issue_ids=[iid], resolution="fixed")
        assert result["count"] == 1
        assert iid in result["resolved"]

    def test_resolve_issue_invalid_resolution(self, workspace, monkeypatch):
        iid = add_comment(workspace["id"], scope="review", text="Test issue", resolution="open")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_review_issue
        result = workspace_resolve_review_issue(issue_ids=[iid], resolution="wontfix")
        assert "error" in result
        assert result["errorCategory"] == "validation"
        assert result["isRetryable"] is False

    def test_resolve_issue_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_review_issue
        result = workspace_resolve_review_issue(issue_ids=[9999], resolution="fixed")
        assert result["count"] == 0
        assert 9999 in result["not_found"]

    def test_resolve_false_positive(self, workspace, monkeypatch):
        iid = add_comment(workspace["id"], scope="review", text="Test issue", resolution="open")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_review_issue
        result = workspace_resolve_review_issue(issue_ids=[iid], resolution="false_positive")
        assert result["count"] == 1
        assert iid in result["resolved"]

    def test_resolve_comment_blocked_for_review_scope(self, workspace, monkeypatch):
        cid = add_comment(workspace["id"], scope="review", text="Review finding", resolution="open")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_comment
        result = workspace_resolve_comment(comment_ids=[cid])
        assert result["count"] == 0
        assert cid in result["not_found"]


class TestProgress:
    def test_update_progress_new(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_progress
        result = workspace_update_progress(phase="1.0", summary="Done assessment")
        assert result["ok"]

    def test_update_progress_existing(self, workspace, monkeypatch):
        add_progress(workspace["id"], "1.0", "Initial")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_progress
        result = workspace_update_progress(phase="1.0", summary="Updated")
        assert result["ok"]
        from core.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM progress_entries WHERE workspace_id = ? AND phase = '1.0'",
            (workspace["id"],)
        ).fetchall()
        db.close()
        assert len(rows) == 1
        assert rows[0]["summary"] == "Updated"

    def test_update_progress_no_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_update_progress
        result = workspace_update_progress(phase="1.0", summary="Done")
        assert "error" in result

    def test_update_progress_visible_in_state(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_progress, workspace_get_state
        workspace_update_progress(phase="1.0", summary="Completed assessment phase")
        state = workspace_get_state()
        assert "1.0" in state["progress_summary"]
        assert state["progress_summary"]["1.0"] == "Completed assessment phase"


class TestCriteria:
    def test_propose_criteria(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_propose_criteria
        result = workspace_propose_criteria(type="unit_test", description="Test user service")
        assert result["ok"]
        assert result["criterion"]["source"] == "agent"
        assert result["criterion"]["status"] == "proposed"

    def test_propose_criteria_blocked_before_planning(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_propose_criteria
        result = workspace_propose_criteria(type="unit_test", description="Too early")
        assert "error" in result
        assert result["errorCategory"] == "validation"

    def test_propose_criteria_with_valid_details_json(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_propose_criteria, workspace_get_criteria
        details = json.dumps({"file": "tests/test_user.py", "test_names": ["test_create_user"]})
        result = workspace_propose_criteria(
            type="unit_test", description="User creation test", details_json=details
        )
        assert result["ok"]
        assert result["criterion"]["details"] == {"file": "tests/test_user.py", "test_names": ["test_create_user"]}

        criteria = workspace_get_criteria()["criteria"]
        match = next(c for c in criteria if c["id"] == result["criterion"]["id"])
        assert match["details"] == {"file": "tests/test_user.py", "test_names": ["test_create_user"]}

    def test_propose_criteria_with_invalid_details_json(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_propose_criteria
        result = workspace_propose_criteria(
            type="unit_test", description="Bad JSON", details_json="{not valid json"
        )
        assert "error" in result
        assert "not valid JSON" in result["error"]

    def test_propose_criteria_with_non_object_details_json(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_propose_criteria
        result = workspace_propose_criteria(
            type="unit_test", description="String details", details_json='"just a string"'
        )
        assert "error" in result
        assert "object" in result["error"].lower()

    def test_propose_criteria_invalid_type(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_propose_criteria
        result = workspace_propose_criteria(type="invalid_type", description="Test")
        assert "error" in result

    def test_propose_criteria_no_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_propose_criteria
        result = workspace_propose_criteria(type="unit_test", description="Test")
        assert "error" in result

    def test_propose_all_valid_types(self, workspace, monkeypatch):
        set_phase(workspace["id"], "2.0")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_propose_criteria
        for cr_type in ("unit_test", "integration_test", "bdd_scenario", "custom"):
            result = workspace_propose_criteria(type=cr_type, description=f"Test {cr_type}")
            assert result["ok"], f"Expected ok for type {cr_type}"

    def test_get_criteria(self, workspace, monkeypatch):
        add_criterion(workspace["id"], status="accepted")
        add_criterion(workspace["id"], status="proposed")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_criteria
        result = workspace_get_criteria()
        assert result["count"] == 2
        assert len(result["criteria"]) == 2
        result2 = workspace_get_criteria(status="accepted")
        assert result2["count"] == 1
        assert result2["criteria"][0]["status"] == "accepted"

    def test_get_criteria_empty(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_criteria
        result = workspace_get_criteria()
        assert result == {"criteria": [], "count": 0}

    def test_update_criteria(self, workspace, monkeypatch):
        cid = add_criterion(workspace["id"])
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_criteria
        result = workspace_update_criteria(
            criterion_id=cid,
            description="Updated desc",
            details_json='{"file": "test.py"}',
        )
        assert result["ok"]
        assert result["criterion"]["description"] == "Updated desc"

    def test_update_criteria_nothing(self, workspace, monkeypatch):
        cid = add_criterion(workspace["id"])
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_criteria
        result = workspace_update_criteria(criterion_id=cid)
        assert "error" in result

    def test_update_criteria_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_criteria
        result = workspace_update_criteria(criterion_id=9999, description="Updated")
        assert "error" in result

    def test_update_criteria_description_only(self, workspace, monkeypatch):
        cid = add_criterion(workspace["id"])
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_criteria
        result = workspace_update_criteria(criterion_id=cid, description="New description")
        assert result["ok"]
        assert result["criterion"]["description"] == "New description"

    def test_update_criteria_blocked_if_accepted(self, workspace, monkeypatch):
        from testing_utils import add_criterion
        from core.db import get_db
        criterion_id = add_criterion(workspace["id"], cr_type="unit_test", description="Test")
        db = get_db()
        db.execute("UPDATE acceptance_criteria SET status = 'accepted' WHERE id = ?", (criterion_id,))
        db.commit()
        db.close()

        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_criteria
        result = workspace_update_criteria(criterion_id=criterion_id, description="New desc")
        assert "error" in result
        assert "accepted" in result["error"].lower()

    def test_update_criteria_resets_rejected_to_proposed(self, workspace, monkeypatch):
        from testing_utils import add_criterion
        from core.db import get_db
        criterion_id = add_criterion(workspace["id"], cr_type="unit_test", description="Test")
        db = get_db()
        db.execute("UPDATE acceptance_criteria SET status = 'rejected' WHERE id = ?", (criterion_id,))
        db.commit()
        db.close()

        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_criteria
        result = workspace_update_criteria(criterion_id=criterion_id, description="Fixed desc")
        assert result["ok"]
        assert result.get("status_reset") == "proposed"

        db = get_db()
        row = db.execute("SELECT status FROM acceptance_criteria WHERE id = ?", (criterion_id,)).fetchone()
        db.close()
        assert row["status"] == "proposed"


class TestUpdateVerificationProfile:
    def _create_profile(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_create_verification_profile
        result = workspace_create_verification_profile(
            name="Test Java", language="java", lsp_command="jdtls"
        )
        assert result["ok"]
        return result["id"]

    def test_update_lsp_command(self, workspace, monkeypatch):
        profile_id = self._create_profile(workspace, monkeypatch)
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_verification_profile
        from core.db import get_db
        result = workspace_update_verification_profile(profile_id=profile_id, lsp_command="bash")
        assert result["ok"]
        db = get_db()
        row = db.execute("SELECT lsp_command FROM verification_profiles WHERE id = ?", (profile_id,)).fetchone()
        db.close()
        assert row["lsp_command"] == "bash"

    def test_update_multiple_fields(self, workspace, monkeypatch):
        profile_id = self._create_profile(workspace, monkeypatch)
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_verification_profile
        from core.db import get_db
        result = workspace_update_verification_profile(
            profile_id=profile_id,
            lsp_command="bash",
            lsp_args='["-c", "JAVA_HOME=/usr/lib/jvm/java-17 exec jdtls"]'
        )
        assert result["ok"]
        db = get_db()
        row = db.execute(
            "SELECT lsp_command, lsp_args FROM verification_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        db.close()
        assert row["lsp_command"] == "bash"
        assert row["lsp_args"] == '["-c", "JAVA_HOME=/usr/lib/jvm/java-17 exec jdtls"]'

    def test_update_nonexistent_profile(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_verification_profile
        result = workspace_update_verification_profile(profile_id=9999, lsp_command="bash")
        assert result["error"] == "profile_not_found"
        assert result["errorCategory"] == "not_found"
        assert result["isRetryable"] is False

    def test_update_no_fields(self, workspace, monkeypatch):
        profile_id = self._create_profile(workspace, monkeypatch)
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_verification_profile
        result = workspace_update_verification_profile(profile_id=profile_id)
        assert result["error"] == "no_fields_to_update"
        assert result["errorCategory"] == "validation"
        assert result["isRetryable"] is False


# ---------------------------------------------------------------------------
# Part B — tests for previously-untested tools
# ---------------------------------------------------------------------------

class TestExtendPlan:
    def _seed_plan(self, workspace):
        set_phase(workspace["id"], "2.0")
        from mcp_server import workspace_set_plan
        plan = {
            "description": "Initial plan",
            "systemDiagram": [],
            "execution": [
                {"id": "3.1", "name": "Phase 1",
                 "scope": {"must": ["src/a.py"], "may": []},
                 "tasks": [
                     {"title": "t1", "files": ["src/a.py"], "agent": "middle-backend-engineer"}
                 ]}
            ],
        }
        result = workspace_set_plan(plan=plan)
        assert result["ok"]

    def test_extend_plan_appends_subphase(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace)
        from mcp_server import workspace_extend_plan, workspace_get_plan
        result = workspace_extend_plan(
            subphase={"name": "Added Phase",
                      "tasks": [{"title": "t2", "files": ["src/b.py"],
                                 "agent": "middle-backend-engineer"}]},
            scope={"must": ["src/b.py"], "may": []},
        )
        assert result["ok"] is True
        plan = workspace_get_plan()
        execution_ids = [item["id"] for item in plan["execution"]]
        assert "3.2" in execution_ids

    def test_extend_plan_embeds_scope_in_new_item(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace)
        from mcp_server import workspace_extend_plan, workspace_get_plan, workspace_get_state
        workspace_extend_plan(
            subphase={"name": "Added Phase",
                      "tasks": [{"title": "t2", "files": ["src/b.py"],
                                 "agent": "middle-backend-engineer"}]},
            scope={"must": ["src/b.py"], "may": ["tests/b/"]},
        )
        plan = workspace_get_plan()
        new_item = next(item for item in plan["execution"] if item["id"] == "3.2")
        assert new_item["scope"] == {"must": ["src/b.py"], "may": ["tests/b/"]}

        state = workspace_get_state()
        assert state["scope"]["3.2"] == {"must": ["src/b.py"], "may": ["tests/b/"]}

    def test_extend_plan_requires_tasks(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace)
        from mcp_server import workspace_extend_plan
        result = workspace_extend_plan(
            subphase={"name": "Empty", "tasks": []},
            scope={"must": [], "may": []},
        )
        assert "error" in result
        assert result["errorCategory"] == "validation"
        assert result["isRetryable"] is False

    def test_extend_plan_blocked_before_planning(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        # phase 0 — not past 2.0
        from mcp_server import workspace_extend_plan
        result = workspace_extend_plan(
            subphase={"name": "X",
                      "tasks": [{"title": "t", "files": [], "agent": "a"}]},
            scope={"must": []},
        )
        assert "error" in result
        assert result["errorCategory"] == "validation"


class TestGranularPlanEdits:
    def _seed_plan(self, workspace, num_phases=3):
        set_phase(workspace["id"], "2.0", plan_json=make_plan_json(num_phases),
                  plan_status="approved")

    def _plan_status(self, workspace):
        from core.db import get_db
        db = get_db()
        try:
            return db.execute(
                "SELECT plan_status FROM workspaces WHERE id = ?", (workspace["id"],)
            ).fetchone()["plan_status"]
        finally:
            db.close()

    def test_update_subphase_patches_one_item(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace)
        from mcp_server import workspace_update_subphase, workspace_get_plan
        result = workspace_update_subphase(subphase_id="3.2", name="Reworked")

        assert result["ok"] is True
        assert result["plan_status"] == "pending"
        items = workspace_get_plan()["execution"]
        assert items[1]["name"] == "Reworked"
        assert items[1]["tasks"][0]["title"] == "Task 2"
        assert items[0]["name"] == "Sub-phase 1"
        assert self._plan_status(workspace) == "pending"

    def test_update_subphase_unknown_id_is_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace)
        from mcp_server import workspace_update_subphase
        result = workspace_update_subphase(subphase_id="3.9", name="Nope")

        assert result["errorCategory"] == "not_found"
        assert result["isRetryable"] is False

    def test_update_subphase_without_fields_is_validation_error(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace)
        from mcp_server import workspace_update_subphase
        result = workspace_update_subphase(subphase_id="3.1")

        assert result["errorCategory"] == "validation"

    def test_update_subphase_blocked_before_planning(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_subphase
        result = workspace_update_subphase(subphase_id="3.1", name="Too early")

        assert result["errorCategory"] == "validation"

    def test_delete_subphase_renumbers_remaining(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace)
        from mcp_server import workspace_delete_subphase, workspace_get_plan
        result = workspace_delete_subphase(subphase_id="3.1")

        assert result["ok"] is True
        assert result["execution_ids"] == ["3.1", "3.2"]
        items = workspace_get_plan()["execution"]
        assert [item["name"] for item in items] == ["Sub-phase 2", "Sub-phase 3"]
        assert self._plan_status(workspace) == "pending"

    def test_delete_subphase_refuses_last_item(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace, num_phases=1)
        from mcp_server import workspace_delete_subphase, workspace_get_plan
        result = workspace_delete_subphase(subphase_id="3.1")

        assert result["errorCategory"] == "business"
        assert len(workspace_get_plan()["execution"]) == 1

    def test_delete_subphase_unknown_id_is_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace)
        from mcp_server import workspace_delete_subphase
        result = workspace_delete_subphase(subphase_id="3.8")

        assert result["errorCategory"] == "not_found"

    def test_delete_subphase_blocked_before_planning(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_delete_subphase
        result = workspace_delete_subphase(subphase_id="3.1")

        assert result["errorCategory"] == "validation"

    def test_set_plan_diagrams_replaces_and_keeps_approval(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace, num_phases=1)
        from mcp_server import workspace_set_plan_diagrams, workspace_get_plan
        diagrams = [{"title": "Class Diagram", "diagram": "classDiagram\n  A --> B"}]
        result = workspace_set_plan_diagrams(diagrams=diagrams)

        assert result == {"ok": True, "diagram_count": 1}
        assert workspace_get_plan()["systemDiagram"] == diagrams
        assert self._plan_status(workspace) == "approved"

    def test_set_plan_diagrams_appends(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace, num_phases=1)
        from mcp_server import workspace_set_plan_diagrams, workspace_get_plan
        workspace_set_plan_diagrams(diagrams=[{"title": "First", "diagram": "graph TD"}])
        result = workspace_set_plan_diagrams(
            diagrams=[{"title": "Second", "diagram": "sequenceDiagram\n  A ->> B: hi"}],
            replace=False,
        )

        assert result["diagram_count"] == 2
        titles = [d["title"] for d in workspace_get_plan()["systemDiagram"]]
        assert titles == ["First", "Second"]

    def test_set_plan_diagrams_rejects_malformed_entries(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace, num_phases=1)
        from mcp_server import workspace_set_plan_diagrams
        result = workspace_set_plan_diagrams(diagrams=[{"title": "No body"}])

        assert result["errorCategory"] == "validation"

    def test_set_plan_diagrams_blocked_before_planning(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_set_plan_diagrams
        result = workspace_set_plan_diagrams(
            diagrams=[{"title": "T", "diagram": "graph TD"}])

        assert result["errorCategory"] == "validation"

    def test_set_plan_description_keeps_approval(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace, num_phases=2)
        from mcp_server import workspace_set_plan_description, workspace_get_plan
        result = workspace_set_plan_description(description="Reworded plan")

        assert result["ok"] is True
        plan = workspace_get_plan()
        assert plan["description"] == "Reworded plan"
        assert len(plan["execution"]) == 2
        assert self._plan_status(workspace) == "approved"

    def test_set_plan_description_rejects_blank(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        self._seed_plan(workspace, num_phases=1)
        from mcp_server import workspace_set_plan_description
        result = workspace_set_plan_description(description="   ")

        assert result["errorCategory"] == "validation"

    def test_set_plan_description_blocked_before_planning(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_set_plan_description
        result = workspace_set_plan_description(description="Too early")

        assert result["errorCategory"] == "validation"


class TestDeleteCriteria:
    def test_delete_proposed_criterion(self, workspace, monkeypatch):
        cid = add_criterion(workspace["id"], status="proposed")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_delete_criteria, workspace_get_criteria
        result = workspace_delete_criteria(criterion_id=cid)

        assert result == {"ok": True, "deleted_id": cid}
        assert workspace_get_criteria() == {"criteria": [], "count": 0}

    def test_delete_accepted_criterion_is_refused(self, workspace, monkeypatch):
        cid = add_criterion(workspace["id"], status="accepted")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_delete_criteria, workspace_get_criteria
        result = workspace_delete_criteria(criterion_id=cid)

        assert result["errorCategory"] == "business"
        assert result["isRetryable"] is False
        assert workspace_get_criteria()["count"] == 1

    def test_delete_unknown_criterion_is_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_delete_criteria
        result = workspace_delete_criteria(criterion_id=987654)

        assert result["errorCategory"] == "not_found"


class TestDeleteResearch:
    def test_delete_research_removes_entry(self, workspace, monkeypatch):
        rid = add_research(workspace["id"], topic="ToDelete")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_delete_research, workspace_list_research
        result = workspace_delete_research(id=rid)
        assert result["ok"] is True
        assert result["deleted_id"] == rid
        assert result["deleted"] is True
        remaining = workspace_list_research()
        assert all(e["id"] != rid for e in remaining)

    def test_delete_research_already_deleted_is_idempotent(self, workspace, monkeypatch):
        rid = add_research(workspace["id"], topic="ToDelete")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_delete_research
        first = workspace_delete_research(id=rid)
        assert first["ok"] is True
        assert first["deleted"] is True

        second = workspace_delete_research(id=rid)
        assert second["ok"] is True
        assert second["deleted_id"] == rid
        assert second["deleted"] is False
        assert "error" not in second

    def test_delete_research_unknown_id_is_idempotent(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_delete_research
        result = workspace_delete_research(id=424242)
        assert result["ok"] is True
        assert result["deleted_id"] == 424242
        assert result["deleted"] is False
        assert "error" not in result


class TestPostComment:
    def test_post_comment_persists(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_post_comment, workspace_get_comments
        result = workspace_post_comment(
            file_path="src/main.py",
            line_start=1,
            line_end=5,
            text="Needs rename",
        )
        assert result["ok"] is True
        comments = workspace_get_comments(scope="review", unresolved_only=False)
        assert any(c.get("text") == "Needs rename" for c in comments)

    def test_post_comment_empty_text_validation(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_post_comment
        result = workspace_post_comment(
            file_path="src/main.py",
            line_start=1,
            line_end=2,
            text="   ",
        )
        assert "error" in result
        assert result["errorCategory"] == "validation"
        assert result["isRetryable"] is False

    def test_post_comment_no_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_post_comment
        result = workspace_post_comment(
            file_path="x.py", line_start=1, line_end=1, text="hi"
        )
        assert "error" in result


class TestSetImpactAnalysis:
    def test_set_impact_analysis_persists_all_fields(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_set_impact_analysis
        result = workspace_set_impact_analysis(
            affected_flows="flow A",
            api_changes="endpoint /x",
            data_flow_changes="data flow X",
            external_dependencies="migration 0010",
            ticket_gaps="no currency spec",
            open_questions="rounding?",
        )
        assert result["ok"] is True

        from core.db import get_db
        db = get_db()
        row = db.execute(
            "SELECT impact_analysis_json FROM workspaces WHERE id = ?",
            (workspace["id"],)
        ).fetchone()
        db.close()
        stored = json.loads(row["impact_analysis_json"])
        assert stored["affected_flows"] == "flow A"
        assert stored["api_changes"] == "endpoint /x"
        assert stored["data_flow_changes"] == "data flow X"
        assert stored["external_dependencies"] == "migration 0010"
        assert stored["ticket_gaps"] == "no currency spec"
        assert stored["open_questions"] == "rounding?"

    def test_set_impact_analysis_no_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_set_impact_analysis
        result = workspace_set_impact_analysis(affected_flows="x")
        assert "error" in result


def _insert_verification_run(workspace_id, phase, status):
    """Insert a completed verification_run row directly, bypassing the MCP layer."""
    from datetime import datetime
    from core.db import get_db

    db = get_db()
    try:
        now = datetime.now().isoformat()
        cursor = db.execute(
            "INSERT INTO verification_runs (workspace_id, phase, status, started_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (workspace_id, phase, status, now, now),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        db.close()


class TestGetVerificationResults:
    def test_empty_when_no_runs(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_verification_results
        result = workspace_get_verification_results()
        assert result == {"runs": [], "empty": True}

    def test_returns_latest_run(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_verification_results
        _insert_verification_run(workspace["id"], "3.1.1", "passed")
        result = workspace_get_verification_results()
        assert result.get("phase") == "3.1.1"
        assert result.get("status") == "passed"

    def test_filters_by_phase(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_verification_results
        _insert_verification_run(workspace["id"], "3.1.1", "passed")
        _insert_verification_run(workspace["id"], "3.2.1", "failed")
        result = workspace_get_verification_results(phase="3.2.1")
        assert result.get("phase") == "3.2.1"
        assert result.get("status") == "failed"


class TestGetVerificationResultsNotFound:
    def test_get_results_with_unknown_run_id_returns_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_verification_results
        result = workspace_get_verification_results(run_id=9999999)
        assert "error" in result
        assert result["errorCategory"] == "not_found"
        assert result.get("run_id") == 9999999

    def test_get_results_no_runs_returns_empty_not_error(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_get_verification_results
        result = workspace_get_verification_results()
        assert result == {"runs": [], "empty": True}


class TestResolveCommentReviewScopeI18n:
    def test_resolve_review_scope_goes_to_not_found_bucket(self, workspace, monkeypatch):
        from core.db import get_db
        cid = add_comment(workspace["id"], scope="review", text="Review finding", resolution="open")
        db = get_db()
        db.execute("UPDATE workspaces SET locale = 'ru' WHERE id = ?", (workspace["id"],))
        db.commit()
        db.close()
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_comment
        result = workspace_resolve_comment(comment_ids=[cid])
        assert result["count"] == 0
        assert cid in result["not_found"]


class TestI18nBlankChecks:
    def test_create_profile_blank_name_message_is_i18n(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_create_verification_profile
        from core.i18n import t
        result = workspace_create_verification_profile(name="", language="go")
        assert result["error"] == t("mcp.error.profileNameRequired")

    def test_update_progress_blank_summary_message_is_i18n(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_progress
        from core.i18n import t
        result = workspace_update_progress(phase="1.0", summary="   ")
        assert result["error"] == t("mcp.error.summaryRequired", "en")


class TestCreateVerificationProfile:
    def test_create_profile_returns_id(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_create_verification_profile
        result = workspace_create_verification_profile(name="Go", language="go")
        assert result["ok"] is True
        assert result["id"] >= 1

    def test_create_profile_blank_name(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_create_verification_profile
        result = workspace_create_verification_profile(name="   ", language="go")
        assert "error" in result
        assert result["errorCategory"] == "validation"

    def test_create_profile_blank_language(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_create_verification_profile
        result = workspace_create_verification_profile(name="Go", language="")
        assert "error" in result
        assert result["errorCategory"] == "validation"


class TestAddVerificationStep:
    def test_add_step_happy_path(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_create_verification_profile, workspace_add_verification_step
        prof = workspace_create_verification_profile(name="Rust", language="rust")
        result = workspace_add_verification_step(
            profile_id=prof["id"], name="Build", command="cargo build"
        )
        assert result["ok"] is True
        assert result["id"] >= 1

    def test_add_step_unknown_profile(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_add_verification_step
        result = workspace_add_verification_step(
            profile_id=909090, name="Build", command="true"
        )
        assert "error" in result
        assert result["errorCategory"] == "not_found"


class TestAssignVerificationProfile:
    def test_assign_profile_happy_path(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_create_verification_profile, workspace_assign_verification_profile
        prof = workspace_create_verification_profile(name="Node", language="node")
        result = workspace_assign_verification_profile(profile_id=prof["id"])
        assert result["ok"] is True
        assert result["id"] >= 1

    def test_assign_profile_already_assigned(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_create_verification_profile, workspace_assign_verification_profile
        prof = workspace_create_verification_profile(name="Py", language="python")
        workspace_assign_verification_profile(profile_id=prof["id"])
        dup = workspace_assign_verification_profile(profile_id=prof["id"])
        assert "error" in dup
        assert dup["errorCategory"] == "business"

    def test_assign_profile_unknown(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_assign_verification_profile
        result = workspace_assign_verification_profile(profile_id=191919)
        assert "error" in result
        assert result["errorCategory"] == "not_found"


# ---------------------------------------------------------------------------
# Part C — contract tests
# ---------------------------------------------------------------------------

EXPECTED_ANNOTATIONS = {
    "workspace_get_state": (True, True, False),
    "workspace_advance": (False, False, False),
    "workspace_set_plan": (False, False, False),
    "workspace_get_plan": (True, True, False),
    "workspace_extend_plan": (False, False, False),
    "workspace_update_subphase": (False, True, False),
    "workspace_delete_subphase": (False, False, True),
    "workspace_set_plan_diagrams": (False, True, False),
    "workspace_set_plan_description": (False, True, False),
    "workspace_post_discussion": (False, False, False),
    "workspace_save_research": (False, False, False),
    "workspace_list_research": (True, True, False),
    "workspace_get_research": (True, True, False),
    "workspace_prove_research": (False, True, False),
    "workspace_delete_research": (False, True, True),
    "workspace_get_comments": (True, True, False),
    "workspace_post_comment": (False, False, False),
    "workspace_resolve_comment": (False, True, False),
    "workspace_submit_review_issue": (False, False, False),
    "workspace_get_review_issues": (True, True, False),
    "workspace_resolve_review_issue": (False, True, False),
    "workspace_update_progress": (False, True, False),
    "workspace_get_progress": (True, True, False),
    "workspace_set_impact_analysis": (False, True, False),
    "workspace_propose_criteria": (False, False, False),
    "workspace_get_criteria": (True, True, False),
    "workspace_update_criteria": (False, True, False),
    "workspace_delete_criteria": (False, False, True),
    "workspace_get_verification_results": (True, True, False),
    "workspace_get_verification_profiles": (True, True, False),
    "workspace_create_verification_profile": (False, False, False),
    "workspace_update_verification_profile": (False, True, False),
    "workspace_add_verification_step": (False, False, False),
    "workspace_assign_verification_profile": (False, True, False),
    "rule_list": (True, True, False),
    "rule_get": (True, True, False),
    "rule_create": (False, False, False),
    "rule_update": (False, True, False),
    "rule_delete": (False, True, True),
    "workspace_review_pipeline_summary": (True, True, False),
    "workspace_submit_proposal": (False, False, False),
    "workspace_get_reflection_context": (True, True, False),
    "workspace_list_proposals": (True, True, False),
    "workspace_resolve_proposal": (False, True, False),
    "workspace_attach_repo": (False, False, False),
    "workspace_save_pr": (False, True, False),
}


class TestMcpToolContracts:
    def _tools(self):
        from mcp_tools import mcp
        return mcp._tool_manager._tools

    def test_all_tools_have_annotations(self):
        from mcp.types import ToolAnnotations
        tools = self._tools()
        assert len(tools) == 46, f"expected 46 registered tools, got {len(tools)}"
        for name, tool in tools.items():
            ann = tool.annotations
            assert ann is not None, f"{name} missing annotations"
            assert isinstance(ann, ToolAnnotations), f"{name} annotations not ToolAnnotations"
            assert isinstance(ann.readOnlyHint, bool), f"{name}.readOnlyHint must be bool, got {ann.readOnlyHint!r}"
            assert isinstance(ann.idempotentHint, bool), f"{name}.idempotentHint must be bool, got {ann.idempotentHint!r}"
            assert isinstance(ann.destructiveHint, bool), f"{name}.destructiveHint must be bool, got {ann.destructiveHint!r}"

    def test_annotations_match_semantics(self):
        tools = self._tools()
        mismatches = []
        for name, expected in EXPECTED_ANNOTATIONS.items():
            assert name in tools, f"tool '{name}' not registered"
            a = tools[name].annotations
            actual = (a.readOnlyHint, a.idempotentHint, a.destructiveHint)
            if actual != expected:
                mismatches.append((name, expected, actual))
        assert not mismatches, f"annotation mismatches: {mismatches}"

    def test_all_registered_tools_are_in_expected_mapping(self):
        # catches regressions: new tools must be added to EXPECTED_ANNOTATIONS
        tools = self._tools()
        extras = set(tools.keys()) - set(EXPECTED_ANNOTATIONS.keys())
        assert not extras, f"tools without declared expected annotations: {extras}"

    def test_all_tools_have_param_descriptions(self):
        import typing
        from pydantic.fields import FieldInfo
        tools = self._tools()
        missing = []
        for name, tool in tools.items():
            fn = tool.fn
            sig = fn.__signature__ if hasattr(fn, "__signature__") else None
            if sig is None:
                import inspect
                sig = inspect.signature(fn)
            for pname, param in sig.parameters.items():
                if pname in ("ws", "project", "db", "locale"):
                    continue
                ann = param.annotation
                origin = typing.get_origin(ann)
                # Annotated[T, Field(...)] → origin is typing.Annotated-related
                if origin is None:
                    missing.append((name, pname, "no Annotated metadata"))
                    continue
                metadata = typing.get_args(ann)[1:]
                has_desc = False
                for m in metadata:
                    if isinstance(m, FieldInfo) and m.description:
                        has_desc = True
                        break
                if not has_desc:
                    missing.append((name, pname, "no Field description"))
        assert not missing, f"params missing descriptions: {missing}"


class TestErrorEnvelopeContract:
    VALID_CATEGORIES = {"transient", "validation", "business", "permission", "not_found"}

    def _assert_envelope(self, result):
        assert isinstance(result, dict), f"expected dict, got {type(result).__name__}: {result}"
        assert "error" in result and isinstance(result["error"], str) and result["error"]
        assert result.get("errorCategory") in self.VALID_CATEGORIES, f"bad category: {result}"
        assert isinstance(result.get("isRetryable"), bool)

    # -- no-workspace envelopes (decorator returns plain {"error": ...}, no category)
    # For no-workspace we only verify "error" present (legacy contract).
    def test_no_workspace_returns_error(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_get_state
        r = workspace_get_state()
        assert "error" in r

    # -- validation envelopes with full structured shape
    def test_update_progress_blank_summary(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_progress
        self._assert_envelope(workspace_update_progress(phase="1.0", summary="   "))

    def test_post_comment_blank_text(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_post_comment
        self._assert_envelope(workspace_post_comment(
            file_path="x.py", line_start=1, line_end=1, text=""
        ))

    def test_submit_review_issue_line_inverted(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_submit_review_issue
        self._assert_envelope(workspace_submit_review_issue(
            file_path="x.py", line_start=5, line_end=1,
            severity="major", description="desc"
        ))

    def test_resolve_review_issue_invalid_resolution(self, workspace, monkeypatch):
        iid = add_comment(workspace["id"], scope="review", text="x", resolution="open")
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_review_issue
        self._assert_envelope(workspace_resolve_review_issue(
            issue_ids=[iid], resolution="nope"
        ))

    def test_resolve_review_issue_empty_list(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_review_issue
        self._assert_envelope(workspace_resolve_review_issue(
            issue_ids=[], resolution="fixed"
        ))

    def test_prove_research_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_prove_research
        self._assert_envelope(workspace_prove_research(id=777777, proven=True))

    def test_delete_research_missing_id_is_idempotent(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_delete_research
        result = workspace_delete_research(id=777777)
        assert result["ok"] is True
        assert result["deleted"] is False

    def test_resolve_comment_empty_list(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_resolve_comment
        self._assert_envelope(workspace_resolve_comment(comment_ids=[]))

    def test_propose_criteria_invalid_type(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_propose_criteria
        self._assert_envelope(workspace_propose_criteria(
            type="invalid_kind", description="x"
        ))

    def test_update_criteria_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_criteria
        self._assert_envelope(workspace_update_criteria(
            criterion_id=99999, description="new"
        ))

    def test_update_verification_profile_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_update_verification_profile
        self._assert_envelope(workspace_update_verification_profile(
            profile_id=9999, lsp_command="x"
        ))

    def test_add_verification_step_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_add_verification_step
        self._assert_envelope(workspace_add_verification_step(
            profile_id=999999, name="Build", command="true"
        ))

    def test_assign_verification_profile_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_assign_verification_profile
        self._assert_envelope(workspace_assign_verification_profile(
            profile_id=999999
        ))

    def test_create_verification_profile_blank(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_create_verification_profile
        self._assert_envelope(workspace_create_verification_profile(
            name="", language="go"
        ))

    def test_set_plan_before_planning(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from mcp_server import workspace_set_plan
        self._assert_envelope(workspace_set_plan(plan={}))


class TestMcpErrorHelper:
    def test_valid_category(self):
        from mcp_tools import mcp_error
        e = mcp_error("validation", "bad", retryable=False)
        assert e["error"] == "bad"
        assert e["errorCategory"] == "validation"
        assert e["isRetryable"] is False
        assert "_invalid_category" not in e

    def test_all_allowed_categories(self):
        from mcp_tools import mcp_error
        for cat in ("transient", "validation", "business", "permission", "not_found"):
            e = mcp_error(cat, "m")
            assert e["errorCategory"] == cat

    def test_invalid_category_falls_back_to_business(self):
        from mcp_tools import mcp_error
        e = mcp_error("totally_wrong", "oops", retryable=True)
        assert e["errorCategory"] == "business"
        assert e["isRetryable"] is True
        assert e["_invalid_category"] == "totally_wrong"
        assert e["error"] == "oops"

    def test_details_merge_into_envelope(self):
        from mcp_tools import mcp_error
        e = mcp_error(
            "not_found", "missing", retryable=False,
            details={"entity_id": 7, "hint": "refresh"}
        )
        assert e["entity_id"] == 7
        assert e["hint"] == "refresh"
        assert e["error"] == "missing"
        assert e["errorCategory"] == "not_found"

    def test_details_cannot_overwrite_reserved_envelope_keys(self):
        from mcp_tools import mcp_error
        # Reserved keys must always reflect the structured arguments, never details.
        e = mcp_error(
            "validation",
            "real",
            retryable=True,
            details={
                "errorCategory": "spoofed",
                "isRetryable": False,
                "error": "fake",
                "_invalid_category": "should_be_ignored",
            },
        )
        assert e["errorCategory"] == "validation"
        assert e["isRetryable"] is True
        assert e["error"] == "real"
        assert "_invalid_category" not in e

    def test_details_non_reserved_keys_still_merge(self):
        from mcp_tools import mcp_error
        e = mcp_error("business", "base", details={"extra": 1})
        assert e["error"] == "base"
        assert e["extra"] == 1

    def test_default_retryable_is_false(self):
        from mcp_tools import mcp_error
        e = mcp_error("validation", "x")
        assert e["isRetryable"] is False


class TestTranslateServiceError:
    def test_known_key_uses_mapping(self):
        from mcp_tools import translate_service_error
        mapping = {"profile_not_found": ("not_found", False)}
        envelope = translate_service_error({"error": "profile_not_found"}, mapping)
        assert envelope["errorCategory"] == "not_found"
        assert envelope["isRetryable"] is False
        assert envelope["error"] == "profile_not_found"

    def test_known_key_shorthand_category(self):
        from mcp_tools import translate_service_error
        mapping = {"some_rule": "validation"}
        envelope = translate_service_error({"error": "some_rule"}, mapping)
        assert envelope["errorCategory"] == "validation"
        assert envelope["isRetryable"] is False
        assert envelope["error"] == "some_rule"

    def test_unknown_key_uses_default(self):
        from mcp_tools import translate_service_error
        envelope = translate_service_error(
            {"error": "unexpected_state"},
            {"known": ("not_found", False)},
            default_category="business",
            default_retryable=False,
        )
        assert envelope["errorCategory"] == "business"
        assert envelope["isRetryable"] is False
        assert envelope["error"] == "unexpected_state"

    def test_preserves_message(self):
        from mcp_tools import translate_service_error
        mapping = {"no_fields_to_update": ("validation", False)}
        envelope = translate_service_error({"error": "no_fields_to_update"}, mapping)
        assert envelope["error"] == "no_fields_to_update"

    def test_default_retryable_flag_respected(self):
        from mcp_tools import translate_service_error
        envelope = translate_service_error(
            {"error": "some_unknown"},
            {},
            default_category="transient",
            default_retryable=True,
        )
        assert envelope["errorCategory"] == "transient"
        assert envelope["isRetryable"] is True


class TestEnvelopeFromStatus:
    def test_404_maps_to_not_found(self):
        from mcp_tools import envelope_from_status
        env = envelope_from_status({"error": "gone"}, 404)
        assert env["errorCategory"] == "not_found"
        assert env["isRetryable"] is False
        assert env["statusCode"] == 404
        assert env["error"] == "gone"

    def test_409_maps_to_business(self):
        from mcp_tools import envelope_from_status
        env = envelope_from_status({"error": "conflict"}, 409)
        assert env["errorCategory"] == "business"
        assert env["isRetryable"] is False
        assert env["statusCode"] == 409

    def test_422_maps_to_validation(self):
        from mcp_tools import envelope_from_status
        env = envelope_from_status({"error": "unprocessable"}, 422)
        assert env["errorCategory"] == "validation"
        assert env["isRetryable"] is False

    def test_400_maps_to_validation(self):
        from mcp_tools import envelope_from_status
        env = envelope_from_status({"error": "bad"}, 400)
        assert env["errorCategory"] == "validation"
        assert env["isRetryable"] is False

    def test_503_maps_to_transient_retryable(self):
        from mcp_tools import envelope_from_status
        env = envelope_from_status({"error": "unavail"}, 503)
        assert env["errorCategory"] == "transient"
        assert env["isRetryable"] is True
        assert env["statusCode"] == 503

    def test_500_maps_to_transient_retryable(self):
        from mcp_tools import envelope_from_status
        env = envelope_from_status({"error": "oops"}, 500)
        assert env["errorCategory"] == "transient"
        assert env["isRetryable"] is True

    def test_unknown_code_falls_back_to_business(self):
        from mcp_tools import envelope_from_status
        env = envelope_from_status({"error": "teapot"}, 418)
        assert env["errorCategory"] == "business"
        assert env["isRetryable"] is False
        assert env["statusCode"] == 418

    def test_missing_error_key_uses_synthetic_message(self):
        from mcp_tools import envelope_from_status
        env = envelope_from_status({}, 404)
        assert env["error"] == "status_404"


class TestWithGlobalDbNoAutoCommit:
    def test_decorator_does_not_autocommit_success_result(self, workspace):
        """with_global_db must NOT commit for the wrapped tool. If the tool omits
        an explicit db.commit(), changes must not persist across connections."""
        from mcp_tools import with_global_db
        from core.db import get_db

        @with_global_db
        def insert_without_commit(db):
            db.execute(
                "INSERT INTO verification_profiles (name, language, origin, created_at) "
                "VALUES ('no-commit-test', 'go', 'user', '2026-04-22T00:00:00')"
            )
            return {"ok": True}

        result = insert_without_commit()
        assert result == {"ok": True}

        fresh = get_db()
        row = fresh.execute(
            "SELECT id FROM verification_profiles WHERE name = 'no-commit-test'"
        ).fetchone()
        fresh.close()
        assert row is None, "row must NOT be visible — the decorator must not auto-commit"

    def test_decorator_commits_when_tool_calls_commit(self, workspace):
        from mcp_tools import with_global_db
        from core.db import get_db

        @with_global_db
        def insert_with_commit(db):
            db.execute(
                "INSERT INTO verification_profiles (name, language, origin, created_at) "
                "VALUES ('explicit-commit', 'go', 'user', '2026-04-22T00:00:00')"
            )
            db.commit()
            return {"ok": True}

        result = insert_with_commit()
        assert result["ok"] is True

        fresh = get_db()
        row = fresh.execute(
            "SELECT id FROM verification_profiles WHERE name = 'explicit-commit'"
        ).fetchone()
        fresh.close()
        assert row is not None

    def test_decorator_rolls_back_on_exception(self):
        """Non-operational exceptions must bubble up; rollback is best-effort."""
        from mcp_tools import with_global_db

        @with_global_db
        def raises_programming_error(db):
            raise ValueError("deliberate failure")

        import pytest
        with pytest.raises(ValueError, match="deliberate failure"):
            raises_programming_error()


class TestNarrowExceptionPropagation:
    def test_non_operational_exception_propagates_from_update_progress(self, workspace, monkeypatch):
        """A non-transient exception inside a tool must propagate instead of being
        wrapped into a transient envelope."""
        monkeypatch.chdir(workspace["working_dir"])
        from services import progress_service

        def raise_type_error(*args, **kwargs):
            raise TypeError("deliberate non-operational failure")

        monkeypatch.setattr(progress_service, "update_progress", raise_type_error)
        from mcp_server import workspace_update_progress

        import pytest
        with pytest.raises(TypeError, match="deliberate non-operational failure"):
            workspace_update_progress(phase="1.0", summary="Non-operational raises.")

    def test_operational_error_is_wrapped_as_transient(self, workspace, monkeypatch):
        import sqlite3
        monkeypatch.chdir(workspace["working_dir"])
        from services import progress_service

        def raise_op_error(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(progress_service, "update_progress", raise_op_error)
        from mcp_server import workspace_update_progress
        result = workspace_update_progress(phase="1.0", summary="OpError path.")
        assert result["errorCategory"] == "transient"
        assert result["isRetryable"] is True


class TestReviewPipelineSummary:
    def test_no_workspace_returns_not_found(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from mcp_server import workspace_review_pipeline_summary
        result = workspace_review_pipeline_summary()
        assert result.get("errorCategory") == "not_found"

    def test_no_run_tracked_returns_not_found(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from services import review_pipeline_service
        review_pipeline_service._STATUS.pop(workspace["id"], None)
        from mcp_server import workspace_review_pipeline_summary
        result = workspace_review_pipeline_summary()
        assert result.get("errorCategory") == "not_found"
        assert result.get("workspace_id") == workspace["id"]

    def test_returns_summary_when_run_tracked(self, workspace, monkeypatch):
        monkeypatch.chdir(workspace["working_dir"])
        from services import review_pipeline_service
        status = review_pipeline_service.PipelineStatus(
            workspace_id=workspace["id"], state="done"
        )
        status.files = {
            "src/a.py": review_pipeline_service.FileResult(
                file="src/a.py", status="done", findings_count=0
            ),
        }
        status.integration = {
            "architecture-reviewer": "done",
            "correctness-reviewer": "done",
        }
        review_pipeline_service._set_status(status)
        try:
            from mcp_server import workspace_review_pipeline_summary
            result = workspace_review_pipeline_summary()
            assert result["workspace_id"] == workspace["id"]
            assert result["is_complete"] is True
            assert result["is_ok"] is True
            assert result["files_total"] == 1
            assert result["files_done"] == 1
            assert result["integration_total"] == 2
        finally:
            review_pipeline_service._STATUS.pop(workspace["id"], None)
