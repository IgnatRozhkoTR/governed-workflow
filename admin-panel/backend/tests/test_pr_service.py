"""Tests for services/pr_service.py: PR tracking per workspace."""
import pytest

from core.db import get_db
from services import pr_service, repo_service


def test_save_pr_inserts_new_row_for_null_repo_id(workspace):
    db = get_db()
    try:
        result = pr_service.save_pr(db, workspace["id"], "https://example.com/pr/1", repo_id=None, title="My PR")
    finally:
        db.close()

    assert result["url"] == "https://example.com/pr/1"
    assert result["title"] == "My PR"
    assert result["repo_id"] is None
    assert result["workspace_id"] == workspace["id"]


def test_save_pr_upserts_by_workspace_and_null_repo_id(workspace):
    db = get_db()
    try:
        first = pr_service.save_pr(db, workspace["id"], "https://example.com/pr/1")
        second = pr_service.save_pr(
            db, workspace["id"], "https://example.com/pr/1-updated", title="Updated"
        )
        prs = pr_service.list_prs(db, workspace["id"])
    finally:
        db.close()

    assert first["id"] == second["id"]
    assert len(prs) == 1
    assert prs[0]["url"] == "https://example.com/pr/1-updated"
    assert prs[0]["title"] == "Updated"


def test_save_pr_upserts_by_workspace_and_repo_id(project, workspace):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]

        first = pr_service.save_pr(db, workspace["id"], "https://example.com/pr/1", repo_id=repo_id)
        second = pr_service.save_pr(
            db, workspace["id"], "https://example.com/pr/1-updated", repo_id=repo_id
        )
        prs = pr_service.list_prs(db, workspace["id"])
    finally:
        db.close()

    assert first["id"] == second["id"]
    assert len(prs) == 1
    assert prs[0]["url"] == "https://example.com/pr/1-updated"


def test_save_pr_treats_null_repo_id_as_distinct_from_repo_scoped_row(project, workspace):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]

        project_wide = pr_service.save_pr(db, workspace["id"], "https://example.com/pr/1", repo_id=None)
        repo_scoped = pr_service.save_pr(db, workspace["id"], "https://example.com/pr/2", repo_id=repo_id)
        prs = pr_service.list_prs(db, workspace["id"])
    finally:
        db.close()

    assert project_wide["id"] != repo_scoped["id"]
    assert len(prs) == 2


@pytest.mark.parametrize("bad_url", ["ftp://example.com/pr/1", "example.com/pr/1", ""])
def test_save_pr_rejects_url_without_http_scheme(workspace, bad_url):
    db = get_db()
    try:
        with pytest.raises(ValueError):
            pr_service.save_pr(db, workspace["id"], bad_url)
    finally:
        db.close()


def test_list_prs_joins_repo_rel_path_and_name(project, workspace):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]
        pr_service.save_pr(db, workspace["id"], "https://example.com/pr/2", repo_id=repo_id, title="Repo PR")

        prs = pr_service.list_prs(db, workspace["id"])
    finally:
        db.close()

    assert prs[0]["rel_path"] == "service-a"
    assert prs[0]["name"] == "service-a"


def test_list_prs_leaves_rel_path_none_for_project_wide_pr(workspace):
    db = get_db()
    try:
        pr_service.save_pr(db, workspace["id"], "https://example.com/pr/1")
        prs = pr_service.list_prs(db, workspace["id"])
    finally:
        db.close()

    assert prs[0]["rel_path"] is None
    assert prs[0]["name"] is None


def test_list_prs_scoped_to_workspace(workspace, second_workspace):
    db = get_db()
    try:
        pr_service.save_pr(db, workspace["id"], "https://example.com/pr/1")
        pr_service.save_pr(db, second_workspace["id"], "https://example.com/pr/2")

        prs = pr_service.list_prs(db, workspace["id"])
    finally:
        db.close()

    assert len(prs) == 1
    assert prs[0]["url"] == "https://example.com/pr/1"


def test_delete_pr_removes_row_and_returns_true(workspace):
    db = get_db()
    try:
        created = pr_service.save_pr(db, workspace["id"], "https://example.com/pr/1")
        deleted = pr_service.delete_pr(db, workspace["id"], created["id"])
        remaining = pr_service.list_prs(db, workspace["id"])
    finally:
        db.close()

    assert deleted is True
    assert remaining == []


def test_delete_pr_returns_false_when_not_found(workspace):
    db = get_db()
    try:
        result = pr_service.delete_pr(db, workspace["id"], 99999)
    finally:
        db.close()
    assert result is False


def test_delete_pr_is_scoped_to_workspace(workspace, second_workspace):
    db = get_db()
    try:
        created = pr_service.save_pr(db, workspace["id"], "https://example.com/pr/1")
        deleted = pr_service.delete_pr(db, second_workspace["id"], created["id"])
        remaining = pr_service.list_prs(db, workspace["id"])
    finally:
        db.close()

    assert deleted is False
    assert len(remaining) == 1
