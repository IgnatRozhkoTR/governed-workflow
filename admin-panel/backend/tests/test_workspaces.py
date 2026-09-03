import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from testing_utils import _git


def test_all_repo_default_asset_dirs_target_dotclaude():
    from routes.workspaces import _REPO_DEFAULT_ASSET_DIRS
    for _src, dst in _REPO_DEFAULT_ASSET_DIRS:
        assert dst.parts[0] == ".claude", f"asset destination {dst} must live under .claude, not {dst.parts[0]}"


def test_list_branches(client, project):
    r = client.get(f"/api/projects/{project['id']}/branches")
    assert r.status_code == 200
    assert "develop" in r.json["local"]


def test_list_branches_not_found(client):
    r = client.get("/api/projects/nonexistent/branches")
    assert r.status_code == 404


def test_list_workspaces_empty(client, project):
    r = client.get(f"/api/projects/{project['id']}/workspaces")
    assert r.status_code == 200
    assert r.json["workspaces"] == []


def test_create_workspace(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/new-ws", "source": "develop", "worktree": True},
    )
    assert r.status_code == 201
    assert r.json["branch"] == "feature/new-ws"


def test_create_workspace_creates_scratchpad_dir_and_registers_exclude(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/scratchpad-setup", "source": "develop", "worktree": True},
    )
    assert r.status_code == 201, r.json

    working_dir = Path(r.json["working_dir"])
    scratchpad_dir = working_dir / ".claude" / "scratchpad"
    assert scratchpad_dir.is_dir()

    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "info/exclude"],
        cwd=str(working_dir), check=True, capture_output=True, text=True,
    )
    exclude_path = Path(result.stdout.strip())
    if not exclude_path.is_absolute():
        exclude_path = working_dir / exclude_path
    assert exclude_path.exists()
    assert ".claude/scratchpad/" in exclude_path.read_text().splitlines()


def test_create_workspace_no_worktree(client, project):
    _git(project["path"], "checkout", "-b", "other-branch")
    _git(project["path"], "checkout", "develop")
    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "other-branch", "source": "develop", "worktree": False},
    )
    assert r.status_code in (201, 409)


def test_create_workspace_missing_branch(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"source": "develop"},
    )
    assert r.status_code == 400


def test_create_workspace_missing_source(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/test-src", "source": "nonexistent-branch"},
    )
    assert r.status_code == 404


def test_create_workspace_duplicate(client, project):
    client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/dup", "source": "develop", "worktree": True},
    )
    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/dup", "source": "develop", "worktree": True},
    )
    assert r.status_code == 409


def test_list_workspaces_after_create(client, project):
    client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/listed", "source": "develop", "worktree": True},
    )
    r = client.get(f"/api/projects/{project['id']}/workspaces")
    assert r.status_code == 200
    assert len(r.json["workspaces"]) >= 1


def test_archive_workspace(client, workspace, project):
    r = client.put(f"/api/ws/{project['id']}/feature/test/archive")
    assert r.status_code == 200
    assert r.json["status"] == "archived"


def test_archive_workspace_not_found(client, project):
    r = client.put(f"/api/ws/{project['id']}/nonexistent/archive")
    assert r.status_code == 404


def test_archive_workspace_already_archived(client, workspace, project):
    client.put(f"/api/ws/{project['id']}/feature/test/archive")
    r = client.put(f"/api/ws/{project['id']}/feature/test/archive")
    # After archiving, sanitized_branch gains a timestamp suffix so the second
    # lookup by the original branch name finds no active workspace.
    assert r.status_code == 404


def test_archive_workspace_rejects_open_proposals(client, workspace, project):
    from core.db import get_db
    from services import proposal_service

    db = get_db()
    try:
        proposal_id = proposal_service.create_proposal(
            db,
            workspace_id=workspace["id"],
            project_id=project["id"],
            type="rule_new",
            implementation_kind="manual",
            title="Dangling proposal",
            body="should be rejected on archive",
        )
    finally:
        db.close()

    r = client.put(f"/api/ws/{project['id']}/feature/test/archive")
    assert r.status_code == 200

    db = get_db()
    try:
        row = db.execute(
            "SELECT status, reason FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
    finally:
        db.close()
    assert row["status"] == "rejected"
    assert row["reason"] == "Workspace archived"


def test_create_workspace_recovers_from_stale_worktree_dir(client, project):
    """A leftover directory at .claude/worktrees/<branch> with no registered
    git worktree should be cleaned up automatically on workspace creation."""
    stale_dir = Path(project["path"]) / ".claude" / "worktrees" / "MP-12"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "leftover.txt").write_text("orphan")

    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "MP-12", "source": "develop", "worktree": True},
    )

    assert r.status_code == 201, r.json
    assert r.json["branch"] == "MP-12"
    assert stale_dir.exists()


def test_create_workspace_returns_409_with_details_when_worktree_add_fails(
    client, project, monkeypatch
):
    """When git worktree add fails, the response must expose stderr in
    `details`, return 409, and leave no phantom workspace row in the DB."""
    from core.db import get_db
    from routes import workspaces as workspaces_module

    real_run_git = workspaces_module.run_git

    def fake_run_git(cwd, *args):
        if args[:2] == ("worktree", "add"):
            return False, "", "fatal: simulated worktree add failure"
        return real_run_git(cwd, *args)

    monkeypatch.setattr(workspaces_module, "run_git", fake_run_git)

    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/worktree-fail", "source": "develop", "worktree": True},
    )

    assert r.status_code == 409
    assert "error" in r.json
    assert r.json["details"] == "fatal: simulated worktree add failure"

    db = get_db()
    try:
        row = db.execute(
            "SELECT id FROM workspaces WHERE project_id = ? AND branch = ?",
            (project["id"], "feature/worktree-fail"),
        ).fetchone()
    finally:
        db.close()
    assert row is None


def test_create_workspace_friendly_error_when_worktree_path_exists(
    client, project, monkeypatch
):
    """When stderr indicates the target path already exists, the response
    must surface a path-specific error message instead of the generic one."""
    from routes import workspaces as workspaces_module

    real_run_git = workspaces_module.run_git

    def fake_run_git(cwd, *args):
        if args[:2] == ("worktree", "add"):
            return False, "", "fatal: '/some/path' already exists"
        return real_run_git(cwd, *args)

    monkeypatch.setattr(workspaces_module, "run_git", fake_run_git)

    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/exists", "source": "develop", "worktree": True},
    )

    assert r.status_code == 409
    assert "already exists" in r.json["error"]
    assert r.json["details"] == "fatal: '/some/path' already exists"


# ─── BASE BRANCH SYNC TESTS ───────────────────────────────────────────────────

from testing_utils import GIT_ENV


@pytest.fixture
def project_with_origin(project, tmp_path):
    """Point the project's local repo at a real origin remote for base-sync tests."""
    origin_path = tmp_path / "origin.git"
    _git(project["path"], "init", "--bare", str(origin_path))
    _git(project["path"], "remote", "add", "origin", str(origin_path))
    _git(project["path"], "push", "origin", "develop:develop")
    return project


def _head_sha(repo_path):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_path), capture_output=True, text=True, env=GIT_ENV
    ).stdout.strip()


def test_create_workspace_base_sync_fast_forwards_stale_local_branch(client, project_with_origin):
    project = project_with_origin
    project_path = project["path"]

    _git(project_path, "checkout", "-b", "main")
    old_sha = _head_sha(project_path)
    (Path(project_path) / "advance.txt").write_text("advance main")
    _git(project_path, "add", "advance.txt")
    _git(project_path, "commit", "-m", "advance main")
    new_sha = _head_sha(project_path)
    _git(project_path, "push", "origin", "main:main")
    _git(project_path, "reset", "--hard", old_sha)
    _git(project_path, "checkout", "develop")

    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/from-main", "source": "main", "worktree": True},
    )

    assert r.status_code == 201, r.json
    base_sync = r.json["base_sync"]
    assert base_sync["attempted"] is True
    assert base_sync["updated"] is True
    assert base_sync["reason"] == f"updated-from {old_sha[:7]} to {new_sha[:7]}"
    assert base_sync["before"] == old_sha[:7]
    assert base_sync["after"] == new_sha[:7]

    local_main = subprocess.run(
        ["git", "rev-parse", "refs/heads/main"], cwd=project_path, capture_output=True, text=True, env=GIT_ENV
    ).stdout.strip()
    assert local_main == new_sha


def test_create_workspace_base_sync_skips_when_base_checked_out(client, project_with_origin):
    project = project_with_origin

    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/from-develop", "source": "develop", "worktree": True},
    )

    assert r.status_code == 201, r.json
    assert r.json["base_sync"] == {
        "attempted": False,
        "updated": False,
        "reason": "skipped-checked-out",
    }


def test_create_workspace_base_sync_reports_not_fast_forward_when_diverged(client, project_with_origin, tmp_path):
    project = project_with_origin
    project_path = project["path"]

    _git(project_path, "checkout", "-b", "main")
    base_sha = _head_sha(project_path)
    _git(project_path, "push", "origin", "main:main")

    clone_dir = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(Path(project_path).parent / "origin.git"), str(clone_dir)],
        check=True, capture_output=True, env=GIT_ENV,
    )
    _git(clone_dir, "checkout", "main")
    (clone_dir / "origin_change.txt").write_text("origin advances")
    _git(clone_dir, "add", "origin_change.txt")
    _git(clone_dir, "commit", "-m", "advance origin main")
    _git(clone_dir, "push", "origin", "main")

    (Path(project_path) / "local_change.txt").write_text("local diverges")
    _git(project_path, "add", "local_change.txt")
    _git(project_path, "commit", "-m", "diverge local main")
    diverged_sha = _head_sha(project_path)
    _git(project_path, "checkout", "develop")

    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/from-diverged-main", "source": "main", "worktree": True},
    )

    assert r.status_code == 201, r.json
    base_sync = r.json["base_sync"]
    assert base_sync["attempted"] is True
    assert base_sync["updated"] is False
    assert base_sync["reason"] == "not-fast-forward"

    local_main = subprocess.run(
        ["git", "rev-parse", "refs/heads/main"], cwd=project_path, capture_output=True, text=True, env=GIT_ENV
    ).stdout.strip()
    assert local_main == diverged_sha


def test_create_workspace_base_sync_reports_no_local_branch(client, project_with_origin):
    project = project_with_origin
    project_path = project["path"]

    _git(project_path, "checkout", "-b", "release")
    _git(project_path, "push", "origin", "release:release")
    _git(project_path, "checkout", "develop")
    _git(project_path, "branch", "-D", "release")

    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/from-release", "source": "release", "worktree": True},
    )

    assert r.status_code == 201, r.json
    assert r.json["base_sync"] == {
        "attempted": False,
        "updated": False,
        "reason": "no-local-branch",
    }


def test_create_workspace_base_sync_not_attempted_without_remote(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/no-remote", "source": "develop", "worktree": True},
    )

    assert r.status_code == 201, r.json
    assert r.json["base_sync"] == {
        "attempted": False,
        "updated": False,
        "reason": "not-remote-based",
    }


def test_create_workspace_base_sync_failure_does_not_block_creation(client, project_with_origin, monkeypatch):
    from core.db import get_db
    from routes import workspaces as workspaces_module

    def boom(project_path, base):
        raise RuntimeError("simulated git failure")

    monkeypatch.setattr(workspaces_module, "_sync_local_base_branch", boom)

    r = client.post(
        f"/api/projects/{project_with_origin['id']}/workspaces",
        json={"branch": "feature/sync-boom", "source": "develop", "worktree": True},
    )

    assert r.status_code == 201, r.json
    assert r.json["base_sync"] == {"attempted": False, "updated": False, "reason": "sync-error"}

    db = get_db()
    try:
        row = db.execute(
            "SELECT id FROM workspaces WHERE project_id = ? AND branch = ?",
            (project_with_origin["id"], "feature/sync-boom"),
        ).fetchone()
    finally:
        db.close()
    assert row is not None


# ─── 3.2 MERGE LAYER TESTS ────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[3]  # worktrees/Restructuring
_MD_SEPARATOR = "\n\n---\n\n# Governed Workflow Defaults\n\n"


@pytest.fixture
def project_with_assets(git_repo):
    """Git repo with project-level .claude/, CLAUDE.md and .mcp.json."""
    repo = Path(git_repo)

    # Project-level .claude/agents and .claude/rules
    (repo / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "agents" / "custom.md").write_text("# Custom Project Agent")
    (repo / ".claude" / "rules").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "rules" / "project.md").write_text("# Project Rule")

    # Project-level CLAUDE.md with a unique marker
    (repo / "CLAUDE.md").write_text("PROJECT_CLAUDE_MD_MARKER")

    # Project-level .mcp.json with an extra server
    (repo / ".mcp.json").write_text(json.dumps({
        "mcpServers": {
            "custom": {"command": "echo", "args": ["hello"]}
        }
    }, indent=2))

    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-m", "Add project assets")
    return git_repo


def _import_workspaces_module():
    """Import routes.workspaces directly, bypassing the routes package __init__."""
    import importlib.util, sys
    server_dir = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "routes.workspaces",
        server_dir / "routes" / "workspaces.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("routes.workspaces", mod)
    spec.loader.exec_module(mod)
    return mod


_WORKSPACES = _import_workspaces_module()


def _call_install_worktree_configs(project_path, wt_path):
    """Call the internal bootstrap function with a fresh db connection."""
    from core.db import get_db
    db = get_db()
    try:
        _WORKSPACES._install_worktree_configs(db, project_path, wt_path)
    finally:
        db.close()


class TestMergeLayer:
    """Integration tests for the _merge_project_assets merge logic."""

    def test_project_agent_preserved_in_worktree(self, project_with_assets, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        _call_install_worktree_configs(project_with_assets, wt)
        assert (wt / ".claude" / "agents" / "custom.md").read_text() == "# Custom Project Agent"

    def test_repo_default_agent_also_present(self, project_with_assets, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        _call_install_worktree_configs(project_with_assets, wt)
        # At least one file from the repo default agents dir must be present
        repo_agents = list((REPO_ROOT / "claude" / "agents").glob("*.md"))
        assert repo_agents, "Repo must have at least one default agent file"
        assert (wt / ".claude" / "agents" / repo_agents[0].name).exists()

    def test_claude_md_concatenated_with_separator(self, project_with_assets, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        _call_install_worktree_configs(project_with_assets, wt)
        content = (wt / "CLAUDE.md").read_text()
        assert "PROJECT_CLAUDE_MD_MARKER" in content
        assert _MD_SEPARATOR in content

    def test_claude_md_project_content_appears_first(self, project_with_assets, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        _call_install_worktree_configs(project_with_assets, wt)
        content = (wt / "CLAUDE.md").read_text()
        project_pos = content.index("PROJECT_CLAUDE_MD_MARKER")
        sep_pos = content.index(_MD_SEPARATOR)
        assert project_pos < sep_pos

    def test_claude_md_is_regular_file_not_symlink(self, project_with_assets, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        _call_install_worktree_configs(project_with_assets, wt)
        target = wt / "CLAUDE.md"
        assert target.exists()
        assert not target.is_symlink()

    def test_mcp_json_symlinked_to_project(self, project_with_assets, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        _call_install_worktree_configs(project_with_assets, wt)
        dst_mcp = wt / ".mcp.json"
        assert dst_mcp.is_symlink()
        data = json.loads(dst_mcp.read_text())
        assert "governed-workflow" in data["mcpServers"]
        assert "custom" in data["mcpServers"]

    def test_rules_symlinked_to_project(self, project_with_assets, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        _call_install_worktree_configs(project_with_assets, wt)
        dst_rules = wt / ".claude" / "rules"
        assert dst_rules.is_symlink()
        src_rules = Path(project_with_assets) / ".claude" / "rules"
        assert dst_rules.resolve() == src_rules.resolve()


class TestMergeLayerModuleOverrides:
    """Ordering guarantee: repo default < enabled-module override < project-local."""

    @staticmethod
    def _make_override_module(root: Path, module_id: str, subpath: str, filename: str, content: str) -> Path:
        mod_dir = root / module_id
        mod_dir.mkdir(parents=True)
        (mod_dir / "SKILL.md").write_text(f"---\nname: {module_id}\n---\n")
        override_dir = mod_dir / "override" / subpath
        override_dir.mkdir(parents=True)
        (override_dir / filename).write_text(content)
        return mod_dir

    @staticmethod
    def _enable_module(db, module_id: str, enabled_at: str = "2024-01-01T00:00:00") -> None:
        db.execute(
            "INSERT INTO modules_enabled (module_id, enabled_at) VALUES (?, ?)",
            (module_id, enabled_at),
        )
        db.commit()

    def test_module_override_fills_gap_left_by_defaults_and_project(self, project_with_assets, tmp_path):
        """A module override supplies a file neither the repo defaults nor the
        project provide, landing in the worktree via the fill-missing pass."""
        from core.db import get_db

        modules_root = tmp_path / "modules"
        self._make_override_module(modules_root, "mod-a", "hooks", "module-hook.md", "# From module override")

        wt = tmp_path / "wt"
        wt.mkdir()
        db = get_db()
        try:
            self._enable_module(db, "mod-a")
            with patch.object(_WORKSPACES, "_MODULE_OVERRIDE_ROOTS", [modules_root]):
                _WORKSPACES._install_worktree_configs(db, project_with_assets, wt)
        finally:
            db.close()

        assert (wt / ".claude" / "hooks" / "module-hook.md").read_text() == "# From module override"
        # Existing project-local precedence is unaffected by the module toggle.
        assert (wt / ".claude" / "agents" / "custom.md").read_text() == "# Custom Project Agent"

    def test_module_override_wins_over_repo_default_on_collision(self, project_with_assets, tmp_path):
        """An override for an existing repo-default agent filename wins over the default."""
        from core.db import get_db

        modules_root = tmp_path / "modules"
        self._make_override_module(
            modules_root, "mod-a", "agents", "middle-backend-engineer.md",
            "# Module override of a real default agent",
        )

        wt = tmp_path / "wt"
        wt.mkdir()
        db = get_db()
        try:
            self._enable_module(db, "mod-a")
            with patch.object(_WORKSPACES, "_MODULE_OVERRIDE_ROOTS", [modules_root]):
                _WORKSPACES._install_worktree_configs(db, project_with_assets, wt)
        finally:
            db.close()

        assert (wt / ".claude" / "agents" / "middle-backend-engineer.md").read_text() == (
            "# Module override of a real default agent"
        )

    def test_project_local_file_wins_over_colliding_module_override(self, project_with_assets, tmp_path):
        """Project always wins: project-local agents/custom.md beats a module override
        shipped for the exact same relative path."""
        from core.db import get_db

        modules_root = tmp_path / "modules"
        self._make_override_module(
            modules_root, "mod-a", "agents", "custom.md", "# From module override, should lose",
        )

        wt = tmp_path / "wt"
        wt.mkdir()
        db = get_db()
        try:
            self._enable_module(db, "mod-a")
            with patch.object(_WORKSPACES, "_MODULE_OVERRIDE_ROOTS", [modules_root]):
                _WORKSPACES._install_worktree_configs(db, project_with_assets, wt)
        finally:
            db.close()

        assert (wt / ".claude" / "agents" / "custom.md").read_text() == "# Custom Project Agent"

    def test_disabled_module_override_not_applied(self, project_with_assets, tmp_path):
        """A module directory that exists on disk but is not enabled contributes nothing."""
        from core.db import get_db

        modules_root = tmp_path / "modules"
        self._make_override_module(modules_root, "mod-a", "hooks", "module-hook.md", "# Should not appear")

        wt = tmp_path / "wt"
        wt.mkdir()
        db = get_db()
        try:
            with patch.object(_WORKSPACES, "_MODULE_OVERRIDE_ROOTS", [modules_root]):
                _WORKSPACES._install_worktree_configs(db, project_with_assets, wt)
        finally:
            db.close()

        assert not (wt / ".claude" / "hooks" / "module-hook.md").exists()

    def test_checkout_fill_missing_uses_module_override_when_destination_missing(self, tmp_path):
        """_fill_missing_repo_defaults (checkout mode's fill pass) picks up a module
        override file for a destination that does not already exist."""
        from core.db import get_db

        modules_root = tmp_path / "modules"
        self._make_override_module(modules_root, "mod-a", "rules", "custom-rule.md", "# Module rule override")

        target = tmp_path / "target"
        target.mkdir()

        db = get_db()
        try:
            self._enable_module(db, "mod-a")
            with patch.object(_WORKSPACES, "_MODULE_OVERRIDE_ROOTS", [modules_root]):
                _WORKSPACES._fill_missing_repo_defaults(db, target)
        finally:
            db.close()

        assert (target / ".claude" / "rules" / "custom-rule.md").read_text() == "# Module rule override"

    def test_checkout_fill_missing_never_overwrites_existing_destination_file(self, tmp_path):
        """Fill-missing semantics hold even when a module ships an override for an
        already-populated destination: checkout mode never overwrites."""
        from core.db import get_db

        modules_root = tmp_path / "modules"
        self._make_override_module(modules_root, "mod-a", "rules", "custom-rule.md", "# Module rule override")

        target = tmp_path / "target"
        (target / ".claude" / "rules").mkdir(parents=True)
        (target / ".claude" / "rules" / "custom-rule.md").write_text("# Pre-existing file")

        db = get_db()
        try:
            self._enable_module(db, "mod-a")
            with patch.object(_WORKSPACES, "_MODULE_OVERRIDE_ROOTS", [modules_root]):
                _WORKSPACES._fill_missing_repo_defaults(db, target)
        finally:
            db.close()

        assert (target / ".claude" / "rules" / "custom-rule.md").read_text() == "# Pre-existing file"


class TestWriteWorkspaceSettingsUnion:
    """Unit tests for the hook-array union logic in _write_workspace_settings."""

    def test_governed_hooks_written_when_no_existing(self, tmp_path):
        settings = tmp_path / ".claude" / "settings.json"
        _WORKSPACES._write_workspace_settings(settings)
        data = json.loads(settings.read_text())
        assert "SessionStart" in data["hooks"]
        assert "PreToolUse" in data["hooks"]

    def test_existing_unrelated_hooks_preserved(self, tmp_path):
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "hooks": {
                "PostToolUse": [{"matcher": "Read", "hooks": [{"type": "command", "command": "echo done"}]}]
            }
        }
        settings.write_text(json.dumps(existing))
        _WORKSPACES._write_workspace_settings(settings)
        data = json.loads(settings.read_text())
        assert "PostToolUse" in data["hooks"]
        assert "SessionStart" in data["hooks"]

    def test_duplicate_governed_hook_not_added_twice(self, tmp_path):
        settings = tmp_path / ".claude" / "settings.json"
        _WORKSPACES._write_workspace_settings(settings)
        count_before = len(json.loads(settings.read_text())["hooks"]["SessionStart"])
        _WORKSPACES._write_workspace_settings(settings)
        count_after = len(json.loads(settings.read_text())["hooks"]["SessionStart"])
        assert count_before == count_after

    def test_conflicting_entry_not_duplicated(self, tmp_path):
        governed_entry = _WORKSPACES._WORKSPACE_HOOKS["hooks"]["SessionStart"][0]
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"hooks": {"SessionStart": [governed_entry]}}))
        _WORKSPACES._write_workspace_settings(settings)
        data = json.loads(settings.read_text())
        matching = [e for e in data["hooks"]["SessionStart"] if e == governed_entry]
        assert len(matching) == 1

    def test_writeWorkspaceSettings_shouldIncludeBlockOrchestratorHook_whenCreatingFreshSettings(self, tmp_path):
        settings = tmp_path / ".claude" / "settings.json"
        _WORKSPACES._write_workspace_settings(settings)
        data = json.loads(settings.read_text())
        pre_tool_use = data["hooks"]["PreToolUse"]
        block_entries = [
            e for e in pre_tool_use
            if any("block-orchestrator-writes.py" in h.get("command", "") for h in e.get("hooks", []))
        ]
        assert len(block_entries) >= 1
        assert block_entries[0]["matcher"] == _WORKSPACES.BLOCK_ORCHESTRATOR_MATCHER

    def test_writeWorkspaceSettings_shouldPreserveBlockOrchestratorHook_whenMergingIntoExistingSettings(self, tmp_path):
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        unrelated_entry = {"matcher": "Read", "hooks": [{"type": "command", "command": "python3 /some/other.py"}]}
        settings.write_text(json.dumps({"hooks": {"PreToolUse": [unrelated_entry]}}))
        _WORKSPACES._write_workspace_settings(settings)
        data = json.loads(settings.read_text())
        pre_tool_use = data["hooks"]["PreToolUse"]
        matchers = [e["matcher"] for e in pre_tool_use]
        assert "Read" in matchers
        block_entries = [
            e for e in pre_tool_use
            if any("block-orchestrator-writes.py" in h.get("command", "") for h in e.get("hooks", []))
        ]
        assert len(block_entries) >= 1

    def test_writeWorkspaceSettings_shouldNotDuplicateBlockOrchestratorHook_whenSettingsAlreadyContainIt(self, tmp_path):
        governed_pre_tool_use = _WORKSPACES._WORKSPACE_HOOKS["hooks"]["PreToolUse"]
        block_entry = next(
            e for e in governed_pre_tool_use
            if any("block-orchestrator-writes.py" in h.get("command", "") for h in e.get("hooks", []))
        )
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"hooks": {"PreToolUse": [block_entry]}}))
        _WORKSPACES._write_workspace_settings(settings)
        data = json.loads(settings.read_text())
        pre_tool_use = data["hooks"]["PreToolUse"]
        block_entries = [
            e for e in pre_tool_use
            if any("block-orchestrator-writes.py" in h.get("command", "") for h in e.get("hooks", []))
        ]
        assert len(block_entries) == 1

    def test_write_workspace_settings_enables_agent_teams(self, tmp_path):
        settings = tmp_path / ".claude" / "settings.json"

        _WORKSPACES._write_workspace_settings(settings)

        data = json.loads(settings.read_text())
        assert data["env"]["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"

    def test_write_workspace_settings_preserves_existing_env(self, tmp_path):
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"env": {"SOME_OTHER": "x"}}))

        _WORKSPACES._write_workspace_settings(settings)

        data = json.loads(settings.read_text())
        assert data["env"]["SOME_OTHER"] == "x"
        assert data["env"]["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"

    def test_write_workspace_settings_hook_merge_unaffected_by_env(self, tmp_path):
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "env": {"SOME_OTHER": "x"},
            "hooks": {
                "PostToolUse": [{"matcher": "Read", "hooks": [{"type": "command", "command": "echo done"}]}]
            }
        }
        settings.write_text(json.dumps(existing))

        _WORKSPACES._write_workspace_settings(settings)

        data = json.loads(settings.read_text())
        assert "PostToolUse" in data["hooks"]
        assert "SessionStart" in data["hooks"]
        assert data["env"]["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"


class TestEnsureWorkspaceMcp:
    """Tests for _ensure_workspace_mcp path normalisation."""

    def test_governed_workflow_entry_written_when_no_file(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"

        _WORKSPACES._ensure_workspace_mcp(mcp_path)

        data = json.loads(mcp_path.read_text())
        entry = data["mcpServers"]["governed-workflow"]
        assert entry["command"] == "python3"
        assert entry["args"] == [_WORKSPACES._MCP_SERVER_PATH]

    def test_stale_governed_workflow_path_overwritten(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"
        stale_path = "/Users/otheruser/x/admin-panel/backend/mcp_server.py"
        mcp_path.write_text(json.dumps({
            "mcpServers": {
                "governed-workflow": {"command": "python3", "args": [stale_path]}
            }
        }, indent=2))

        _WORKSPACES._ensure_workspace_mcp(mcp_path)

        data = json.loads(mcp_path.read_text())
        assert data["mcpServers"]["governed-workflow"]["args"] == [_WORKSPACES._MCP_SERVER_PATH]

    def test_stale_workspace_entry_path_also_fixed(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"
        stale_path = "/Users/otheruser/x/admin-panel/backend/mcp_server.py"
        mcp_path.write_text(json.dumps({
            "mcpServers": {
                "governed-workflow": {"command": "python3", "args": [stale_path]},
                "workspace": {"command": "python3", "args": [stale_path]},
                "gitlab": {"command": "node", "args": ["/usr/local/bin/gitlab-mcp"]}
            }
        }, indent=2))

        _WORKSPACES._ensure_workspace_mcp(mcp_path)

        data = json.loads(mcp_path.read_text())
        assert data["mcpServers"]["governed-workflow"]["args"] == [_WORKSPACES._MCP_SERVER_PATH]
        assert data["mcpServers"]["workspace"]["args"] == [_WORKSPACES._MCP_SERVER_PATH]
        assert data["mcpServers"]["gitlab"]["args"] == ["/usr/local/bin/gitlab-mcp"]

    def test_unrelated_server_preserved_exactly(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(json.dumps({
            "mcpServers": {
                "gitlab": {"command": "node", "args": ["/usr/local/bin/gitlab-mcp"], "env": {"TOKEN": "abc"}}
            }
        }, indent=2))

        _WORKSPACES._ensure_workspace_mcp(mcp_path)

        data = json.loads(mcp_path.read_text())
        gitlab = data["mcpServers"]["gitlab"]
        assert gitlab["command"] == "node"
        assert gitlab["args"] == ["/usr/local/bin/gitlab-mcp"]
        assert gitlab["env"] == {"TOKEN": "abc"}

    def test_malformed_json_recovered_with_governed_workflow_entry(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text("{not valid json,,}")

        _WORKSPACES._ensure_workspace_mcp(mcp_path)

        data = json.loads(mcp_path.read_text())
        assert data["mcpServers"]["governed-workflow"]["args"] == [_WORKSPACES._MCP_SERVER_PATH]


class TestBackupRestoreDirectories:
    """Tests for the expanded backup/restore with _BACKUP_DIRS."""

    def test_backup_creates_directory_copy(self, tmp_path):
        project = tmp_path / "project"
        (project / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        (project / ".claude" / "agents" / "test.md").write_text("# Test")
        _WORKSPACES._backup_project_files(str(project))
        backup_dir = project / ".claude/agents.pre-workspace"
        assert backup_dir.is_dir()
        assert (backup_dir / "test.md").read_text() == "# Test"

    def test_restore_recovers_directory(self, tmp_path):
        project = tmp_path / "project"
        (project / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        (project / ".claude" / "agents" / "test.md").write_text("# Original")
        _WORKSPACES._backup_project_files(str(project))
        (project / ".claude" / "agents" / "test.md").write_text("# Modified")
        _WORKSPACES._restore_project_files(str(project))
        assert (project / ".claude" / "agents" / "test.md").read_text() == "# Original"

    def test_backup_idempotent(self, tmp_path):
        project = tmp_path / "project"
        (project / ".claude" / "agents").mkdir(parents=True)
        (project / ".claude" / "agents" / "x.md").write_text("v1")
        _WORKSPACES._backup_project_files(str(project))
        (project / ".claude" / "agents" / "x.md").write_text("v2")
        _WORKSPACES._backup_project_files(str(project))
        backup = project / ".claude/agents.pre-workspace" / "x.md"
        assert backup.read_text() == "v1"

    def test_restore_removes_backup_dir(self, tmp_path):
        project = tmp_path / "project"
        (project / ".claude" / "agents").mkdir(parents=True)
        (project / ".claude" / "agents" / "x.md").write_text("data")
        _WORKSPACES._backup_project_files(str(project))
        _WORKSPACES._restore_project_files(str(project))
        assert not (project / ".claude/agents.pre-workspace").exists()


class TestHookScriptRepoResolution:
    """Smoke tests for repo-root resolution in hook scripts."""

    HOOKS_DIR = REPO_ROOT / "claude" / "hooks"

    def _run_hook(self, script_name, stdin_data):
        proc = subprocess.run(
            [sys.executable, str(self.HOOKS_DIR / script_name)],
            input=json.dumps(stdin_data).encode(),
            capture_output=True,
            timeout=10,
        )
        return proc

    def test_pre_tool_hook_allows_non_governed_path(self):
        """Hook exits 0 (allow) for a tool not triggering any local deny rule."""
        proc = self._run_hook("pre-tool-hook.py", {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/some-file.txt"},
            "cwd": "/tmp",
        })
        # Exits 0 because Read is not in the deny rules and API is down → allow
        assert proc.returncode == 0

    def test_pre_tool_hook_blocks_admin_panel_curl(self):
        """Hook denies curl to admin panel."""
        proc = self._run_hook("pre-tool-hook.py", {
            "tool_name": "Bash",
            "tool_input": {"command": "curl http://localhost:5111/api/hook/check-permission"},
            "cwd": "/tmp",
        })
        assert proc.returncode == 0
        output = json.loads(proc.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_block_orchestrator_allows_no_agent_id_outside_git(self):
        """block-orchestrator-writes allows when cwd is not inside a git repo."""
        proc = self._run_hook("block-orchestrator-writes.py", {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/somefile.py"},
            "cwd": "/tmp",
        })
        assert proc.returncode == 0

    def test_block_orchestrator_denies_main_orchestrator_file_write(self):
        """Main orchestrator (no agent_id) is denied file writes in git repo."""
        proc = self._run_hook("block-orchestrator-writes.py", {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(REPO_ROOT / "some_file.py")},
            "cwd": str(REPO_ROOT),
            # no agent_id → main orchestrator
        })
        assert proc.returncode == 0
        output = json.loads(proc.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_get_command_config_returns_env_vars(client, workspace, project):
    r = client.get(f"/api/ws/{project['id']}/feature/test/command")
    assert r.status_code == 200
    assert r.json["env_vars"] == ""


def test_update_command_config_persists_env_vars(client, workspace, project):
    env_block = "FOO=bar\nBAZ=qux"
    r = client.put(
        f"/api/ws/{project['id']}/feature/test/command",
        json={"env_vars": env_block},
    )
    assert r.status_code == 200

    r = client.get(f"/api/ws/{project['id']}/feature/test/command")
    assert r.status_code == 200
    assert r.json["env_vars"] == env_block


def test_update_command_config_rerenders_launch_env_file(client, workspace, project):
    r = client.put(
        f"/api/ws/{project['id']}/feature/test/command",
        json={"env_vars": "FOO=bar"},
    )
    assert r.status_code == 200

    launch_env = Path(workspace["working_dir"]) / ".claude" / "state" / "launch-env"
    assert launch_env.read_text() == "export FOO=bar\n"
