"""Tests for services/repo_service.py: multi-repo project registry."""
from pathlib import Path

import pytest

from core.db import get_db
from testing_utils import _git
from services import repo_service


def _make_repo(base_dir, name, branch="develop"):
    repo = base_dir / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "checkout", "-b", branch)
    (repo / ".gitignore").write_text("")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Initial commit")
    return repo


@pytest.fixture
def multi_base_dir(tmp_path):
    """Base folder with two git repos, a non-repo dir, and a node_modules dir."""
    base = tmp_path / "base"
    base.mkdir()
    _make_repo(base, "service-a", branch="develop")
    _make_repo(base, "service-b", branch="main")
    (base / "not-a-repo").mkdir()
    (base / "node_modules").mkdir()
    return base


def test_scan_repos_finds_immediate_git_subdirs_sorted_by_rel_path(multi_base_dir):
    candidates = repo_service.scan_repos(str(multi_base_dir))
    assert [c["rel_path"] for c in candidates] == ["service-a", "service-b"]


def test_scan_repos_reports_name_and_current_branch(multi_base_dir):
    candidates = repo_service.scan_repos(str(multi_base_dir))
    by_path = {c["rel_path"]: c for c in candidates}
    assert by_path["service-a"] == {
        "rel_path": "service-a", "name": "service-a", "current_branch": "develop",
    }
    assert by_path["service-b"]["current_branch"] == "main"


def test_scan_repos_skips_non_repo_dir_and_node_modules(multi_base_dir):
    rel_paths = {c["rel_path"] for c in repo_service.scan_repos(str(multi_base_dir))}
    assert "not-a-repo" not in rel_paths
    assert "node_modules" not in rel_paths


def test_scan_repos_skips_dotdirs_even_when_git_repos(multi_base_dir):
    hidden = multi_base_dir / ".hidden"
    hidden.mkdir()
    _git(hidden, "init")

    rel_paths = {c["rel_path"] for c in repo_service.scan_repos(str(multi_base_dir))}
    assert ".hidden" not in rel_paths


def test_scan_repos_returns_empty_list_for_nonexistent_base_dir(tmp_path):
    assert repo_service.scan_repos(str(tmp_path / "does-not-exist")) == []


def test_set_repos_inserts_new_registry_rows(project):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [
            {"rel_path": "service-a", "base_branch": "develop"},
            {"rel_path": "service-b", "base_branch": "main"},
        ])
        repos = repo_service.list_repos(db, project["id"])
    finally:
        db.close()

    assert [(r["rel_path"], r["base_branch"], r["name"]) for r in repos] == [
        ("service-a", "develop", "service-a"),
        ("service-b", "main", "service-b"),
    ]


def test_set_repos_preserves_id_and_override_for_kept_rows(project):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        original_id = repo_service.list_repos(db, project["id"])[0]["id"]
        repo_service.update_repo(db, project["id"], original_id, git_rules_override="custom rules")

        repo_service.set_repos(db, project["id"], [
            {"rel_path": "service-a", "base_branch": "release"},
            {"rel_path": "service-b", "base_branch": "main"},
        ])
        by_path = {r["rel_path"]: r for r in repo_service.list_repos(db, project["id"])}
        full_a = repo_service.get_repo(db, project["id"], by_path["service-a"]["id"])
    finally:
        db.close()

    assert by_path["service-a"]["id"] == original_id
    assert by_path["service-a"]["base_branch"] == "release"
    assert full_a["git_rules_override"] == "custom rules"


def test_set_repos_deletes_registered_repos_absent_from_selection(project):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [
            {"rel_path": "service-a", "base_branch": "develop"},
            {"rel_path": "service-b", "base_branch": "main"},
        ])
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repos = repo_service.list_repos(db, project["id"])
    finally:
        db.close()

    assert [r["rel_path"] for r in repos] == ["service-a"]


def test_list_repos_derives_has_rules_override_without_exposing_text(project):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]
        repo_service.update_repo(db, project["id"], repo_id, git_rules_override="custom")

        repos = repo_service.list_repos(db, project["id"])
    finally:
        db.close()

    assert repos[0]["has_rules_override"] is True
    assert "git_rules_override" not in repos[0]


def test_get_repo_returns_none_for_unknown_id(project):
    db = get_db()
    try:
        result = repo_service.get_repo(db, project["id"], 99999)
    finally:
        db.close()
    assert result is None


def test_update_repo_partial_base_branch_leaves_override_untouched(project):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]
        repo_service.update_repo(db, project["id"], repo_id, git_rules_override="custom")

        updated = repo_service.update_repo(db, project["id"], repo_id, base_branch="release")
    finally:
        db.close()

    assert updated["base_branch"] == "release"
    assert updated["git_rules_override"] == "custom"


def test_update_repo_explicit_none_clears_override(project):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]
        repo_service.update_repo(db, project["id"], repo_id, git_rules_override="custom")

        updated = repo_service.update_repo(db, project["id"], repo_id, git_rules_override=None)
    finally:
        db.close()

    assert updated["git_rules_override"] is None


def test_update_repo_omitted_override_leaves_it_unchanged(project):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]
        repo_service.update_repo(db, project["id"], repo_id, git_rules_override="custom")

        updated = repo_service.update_repo(db, project["id"], repo_id, base_branch="release")
    finally:
        db.close()

    assert updated["git_rules_override"] == "custom"


def test_update_repo_returns_none_for_unknown_repo(project):
    db = get_db()
    try:
        result = repo_service.update_repo(db, project["id"], 99999, base_branch="release")
    finally:
        db.close()
    assert result is None


def test_resolve_git_rules_uses_repo_override_when_present(project):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]
        repo_service.update_repo(db, project["id"], repo_id, git_rules_override="Repo-specific rules")
        repo_row = repo_service.get_repo(db, project["id"], repo_id)

        result = repo_service.resolve_git_rules(db, project, repo_row)
    finally:
        db.close()

    assert result == "Repo-specific rules"


def test_resolve_git_rules_falls_back_to_project_rules_when_override_empty(project):
    rules_path = Path(project["path"]) / ".claude" / "git-rules.md"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text("Project-wide rules")

    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]
        repo_row = repo_service.get_repo(db, project["id"], repo_id)

        result = repo_service.resolve_git_rules(db, project, repo_row)
    finally:
        db.close()

    assert result == "Project-wide rules"


def test_resolve_git_rules_returns_empty_string_when_neither_configured(project):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]
        repo_row = repo_service.get_repo(db, project["id"], repo_id)

        result = repo_service.resolve_git_rules(db, project, repo_row)
    finally:
        db.close()

    assert result == ""


def test_list_attached_joins_project_repos_fields(project, workspace):
    db = get_db()
    try:
        repo_service.set_repos(db, project["id"], [{"rel_path": "service-a", "base_branch": "develop"}])
        repo_id = repo_service.list_repos(db, project["id"])[0]["id"]
        db.execute(
            "INSERT INTO workspace_repos (workspace_id, repo_id, branch, worktree_path, attached) "
            "VALUES (?, ?, ?, ?, ?)",
            (workspace["id"], repo_id, "feature/x", "/tmp/wt/service-a", "2026-01-01"),
        )
        db.commit()

        attached = repo_service.list_attached(db, workspace["id"])
    finally:
        db.close()

    assert attached == [{
        "rel_path": "service-a",
        "name": "service-a",
        "branch": "feature/x",
        "worktree_path": "/tmp/wt/service-a",
        "base_branch": "develop",
    }]


def test_list_attached_returns_empty_list_when_none_attached(workspace):
    db = get_db()
    try:
        attached = repo_service.list_attached(db, workspace["id"])
    finally:
        db.close()
    assert attached == []
