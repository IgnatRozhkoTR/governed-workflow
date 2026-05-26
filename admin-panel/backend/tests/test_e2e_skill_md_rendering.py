"""End-to-end test: toggling a phase from the REST API rewrites SKILL.md.

Sub-phase 3.1 (plan task 14): exercises the full pipeline — REST PUT →
phase_settings persistence → ConfiguratorChain → SkillConfigurator →
filesystem write — at both the project root and the active worktree.

Uses real filesystem writes (no mocks) so any breakage in the wiring shows up.
The test exercises the install flow (_fill_missing_repo_defaults) to place
SKILL.md.template in the project, then toggles a phase off via the route and
asserts the rendered SKILL.md drops that phase's section while preserving its
neighbours.
"""

from datetime import datetime
from pathlib import Path

import pytest

from core.db import get_db
from core.paths import REPO_ROOT
from routes.workspaces import _fill_missing_repo_defaults


SKILL_TEMPLATE_REL = ".claude/skills/governed-workflow/SKILL.md.template"
SKILL_OUTPUT_REL = ".claude/skills/governed-workflow/SKILL.md"


@pytest.fixture
def project_with_template(tmp_path, clean_db, git_repo):
    """Use the install flow to place SKILL.md.template into ``git_repo`` and register a project."""
    _fill_missing_repo_defaults(Path(git_repo))

    project_id = "e2e-skill-project"
    db = get_db()
    try:
        db.execute(
            "INSERT INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
            (project_id, "E2E Skill Project", git_repo, datetime.now().isoformat()),
        )
        db.commit()
    finally:
        db.close()
    return {"id": project_id, "path": git_repo}


@pytest.fixture
def worktree_workspace(project_with_template, tmp_path):
    """Register a workspace pointing at a distinct working_dir to mimic a worktree."""
    working_dir = tmp_path / "wt-rendering"
    working_dir.mkdir()

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
            "created, status, phase, scope_json, plan_json, source_branch) "
            "VALUES (?, ?, ?, ?, ?, 'active', '0', '{}', '{}', 'develop')",
            (project_with_template["id"], "feature/rendering",
             "feature-rendering", str(working_dir), datetime.now().isoformat()),
        )
        ws_id = cur.lastrowid
        db.commit()
    finally:
        db.close()
    return {
        "id": ws_id,
        "project_id": project_with_template["id"],
        "branch": "feature/rendering",
        "working_dir": working_dir,
    }


def _read_orchestrator_md_state() -> tuple[bytes, Path] | None:
    candidate = REPO_ROOT / "claude" / "agents" / "orchestrator.md"
    if not candidate.exists():
        return None
    return candidate.read_bytes(), candidate


def test_project_phase_toggle_off_removes_section_in_project_skill(
    client, project_with_template, worktree_workspace
):
    """PUTing phase 1.1 off at project scope removes its block from SKILL.md."""
    snapshot = _read_orchestrator_md_state()

    response = client.put(
        f"/api/projects/{project_with_template['id']}/phase-settings",
        json={"settings": {"1.1": False}},
    )
    assert response.status_code == 200

    # (a) DB row reflects the toggle.
    db = get_db()
    try:
        row = db.execute(
            "SELECT enabled FROM phase_settings WHERE scope_type='project' "
            "AND scope_id=? AND phase_id='1.1'",
            (project_with_template["id"],),
        ).fetchone()
    finally:
        db.close()
    assert row is not None and row["enabled"] == 0

    # (b) Project-level SKILL.md exists with the toggled phase ABSENT.
    project_skill = Path(project_with_template["path"]) / SKILL_OUTPUT_REL
    assert project_skill.exists(), "SKILL.md was not rendered at the project root"
    project_body = project_skill.read_text()
    assert "## 1.1 Research" not in project_body
    assert "## 1.0 Assessment" in project_body, "neighbouring phase should still render"
    assert "{{PHASES}}" not in project_body

    # (c) Worktree SKILL.md exists and matches.
    worktree_skill = worktree_workspace["working_dir"] / SKILL_OUTPUT_REL
    assert worktree_skill.exists(), "SKILL.md was not rendered for the worktree"
    assert worktree_skill.read_text() == project_body

    # (d) The shipped orchestrator.md must not be mutated by render.
    if snapshot is not None:
        after_bytes = snapshot[1].read_bytes()
        assert after_bytes == snapshot[0], (
            "claude/agents/orchestrator.md was modified by the configurator chain"
        )


def test_workspace_phase_toggle_off_also_propagates_to_skill(
    client, project_with_template, worktree_workspace
):
    """A workspace-scope toggle still re-renders SKILL.md (chain runs on every save).

    Workspace-scope overrides are *not* honored by resolve_for_project, so the
    toggled phase will still appear in the rendered output, but the chain
    must still be invoked and write a SKILL.md byte-for-byte equal between
    the project root and the active worktree.
    """
    project_skill = Path(project_with_template["path"]) / SKILL_OUTPUT_REL
    worktree_skill = worktree_workspace["working_dir"] / SKILL_OUTPUT_REL

    # Ensure a clean starting state with no SKILL.md yet rendered.
    if project_skill.exists():
        project_skill.unlink()
    if worktree_skill.exists():
        worktree_skill.unlink()

    response = client.put(
        f"/api/ws/{project_with_template['id']}/feature/rendering/phase-settings",
        json={"settings": {"1.1": False}},
    )
    assert response.status_code == 200

    assert project_skill.exists()
    assert worktree_skill.exists()
    body = project_skill.read_text()
    assert worktree_skill.read_text() == body
    assert "{{PHASES}}" not in body
    # Workspace-scope settings do NOT propagate to the project-level render.
    assert "## 1.1 Research" in body


def test_re_enabling_phase_restores_section(client, project_with_template, worktree_workspace):
    """A subsequent toggle back to ``True`` puts the phase block back in SKILL.md."""
    # Toggle off
    off = client.put(
        f"/api/projects/{project_with_template['id']}/phase-settings",
        json={"settings": {"1.1": False}},
    )
    assert off.status_code == 200
    project_skill = Path(project_with_template["path"]) / SKILL_OUTPUT_REL
    assert "## 1.1 Research" not in project_skill.read_text()

    # Toggle back on (pass empty settings to clear; service uses upsert so re-set explicitly)
    on = client.put(
        f"/api/projects/{project_with_template['id']}/phase-settings",
        json={"settings": {"1.1": True}},
    )
    assert on.status_code == 200
    assert "## 1.1 Research" in project_skill.read_text()
