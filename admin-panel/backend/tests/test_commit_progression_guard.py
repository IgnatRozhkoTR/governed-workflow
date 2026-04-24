"""Tests for the commit progression guard on phase 3.N.4.

These verify that ``CommitPhase.validate`` enforces:
- HEAD must equal the submitted commit_hash
- A moving ``last_confirmed_commit`` checkpoint that never regresses
- Each commit's diff stays within the active sub-phase's scope patterns
- Replaying the same commit twice is rejected
- Yolo mode bypasses every advance-side check (checkpoint, descendant, scope).
"""
import json
import subprocess
from pathlib import Path

from advance.orchestrator import perform_advance
from core.db import get_db

from testing_utils import _git, add_progress, make_plan_json, set_phase


def _get_ws_row(ws_id):
    db = get_db()
    row = db.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
    db.close()
    return row


def _setup_execution_phase(ws_id, phase, num_plan_phases=3):
    """Set up workspace for an execution phase with per-sub-phase scope."""
    plan = make_plan_json(num_plan_phases)
    scope = {f"3.{n}": {"must": ["src/"], "may": ["tests/"]} for n in range(1, num_plan_phases + 1)}
    set_phase(
        ws_id, phase,
        plan_json=plan,
        plan_status="approved",
        scope_status="approved",
        scope_json=json.dumps(scope),
    )


def _commit_file(working_dir, relative_path, content, message):
    """Create/modify a file, commit it, and return the commit hash."""
    full = Path(working_dir) / relative_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    _git(working_dir, "add", ".")
    _git(working_dir, "commit", "-m", message)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=working_dir,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _last_confirmed_commit(ws_id):
    db = get_db()
    row = db.execute(
        "SELECT last_confirmed_commit FROM workspaces WHERE id = ?", (ws_id,)
    ).fetchone()
    db.close()
    return row["last_confirmed_commit"]


def test_lazy_init_derives_checkpoint_and_first_commit_passes(workspace, project):
    """First 3.N.4 run with NULL last_confirmed_commit lazy-inits from merge-base
    against the source branch and advances the checkpoint to the submitted hash."""
    _setup_execution_phase(workspace["id"], "3.1.4")
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    commit_hash = _commit_file(
        workspace["working_dir"], "src/feature.py", "print('hi')\n", "Add feature"
    )

    ws = _get_ws_row(workspace["id"])
    assert ws["last_confirmed_commit"] is None

    result, code = perform_advance(ws, project["path"], body={"commit_hash": commit_hash})

    assert code == 200, result
    assert result["phase"] == "3.2.0"
    assert _last_confirmed_commit(workspace["id"]) == commit_hash


def test_second_commit_advances_forward_and_updates_checkpoint(workspace, project):
    """A second commit (descendant of the previous checkpoint, diff in scope) passes."""
    _setup_execution_phase(workspace["id"], "3.1.4")
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    first_hash = _commit_file(
        workspace["working_dir"], "src/first.py", "print('one')\n", "First commit"
    )
    ws = _get_ws_row(workspace["id"])
    _, code = perform_advance(ws, project["path"], body={"commit_hash": first_hash})
    assert code == 200
    assert _last_confirmed_commit(workspace["id"]) == first_hash

    _setup_execution_phase(workspace["id"], "3.2.4")
    add_progress(workspace["id"], "3.2", "Sub-phase 2 complete")

    second_hash = _commit_file(
        workspace["working_dir"], "src/second.py", "print('two')\n", "Second commit"
    )

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": second_hash})

    assert code == 200, result
    assert result["phase"] == "3.3.0"
    assert _last_confirmed_commit(workspace["id"]) == second_hash


def test_replaying_same_commit_is_rejected(workspace, project):
    """Submitting the same commit_hash twice on a fresh sub-phase is blocked by
    the existing phase_history replay check — the guard never has to run."""
    _setup_execution_phase(workspace["id"], "3.1.4")
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    commit_hash = _commit_file(
        workspace["working_dir"], "src/feature.py", "print('hi')\n", "Add feature"
    )

    ws = _get_ws_row(workspace["id"])
    _, code = perform_advance(ws, project["path"], body={"commit_hash": commit_hash})
    assert code == 200

    _setup_execution_phase(workspace["id"], "3.2.4")
    add_progress(workspace["id"], "3.2", "Sub-phase 2 complete")
    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": commit_hash})

    assert code == 422
    assert "already used" in result["message"].lower()


def test_diff_outside_scope_is_rejected(workspace, project):
    """A commit that touches files outside the active sub-phase's must+may scope
    is rejected and the offending file is named in the error message."""
    _setup_execution_phase(workspace["id"], "3.1.4")
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    working_dir = workspace["working_dir"]
    (Path(working_dir) / "src").mkdir(exist_ok=True)
    (Path(working_dir) / "src" / "ok.py").write_text("print('ok')\n")
    (Path(working_dir) / "unauthorized").mkdir(exist_ok=True)
    (Path(working_dir) / "unauthorized" / "evil.py").write_text("print('evil')\n")
    _git(working_dir, "add", ".")
    _git(working_dir, "commit", "-m", "Add file outside scope")
    commit_hash = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=working_dir,
        capture_output=True, text=True,
    ).stdout.strip()

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": commit_hash})

    assert code == 422
    assert "outside the approved sub-phase scope" in result["message"]
    assert "unauthorized/evil.py" in result["message"]


def test_old_commit_not_descendant_is_rejected(workspace, project):
    """Submitting a commit that is not a descendant of last_confirmed_commit is
    rejected with the 'not a descendant' error."""
    _setup_execution_phase(workspace["id"], "3.1.4")
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    working_dir = workspace["working_dir"]

    older_hash = _commit_file(working_dir, "src/older.py", "print('older')\n", "Older commit")
    newer_hash = _commit_file(working_dir, "src/newer.py", "print('newer')\n", "Newer commit")

    db = get_db()
    db.execute(
        "UPDATE workspaces SET last_confirmed_commit = ? WHERE id = ?",
        (newer_hash, workspace["id"])
    )
    db.commit()
    db.close()

    _git(working_dir, "reset", "--hard", older_hash)

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": older_hash})

    assert code == 422
    assert "not a descendant" in result["message"]


def test_yolo_mode_bypasses_commit_progression(workspace, project):
    """Yolo mode skips every advance-side check (HEAD match, descendant,
    scope). A commit that would fail all three progression rules is
    accepted because ``perform_advance`` does not call ``validate`` under
    yolo."""
    _setup_execution_phase(workspace["id"], "3.1.4")
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    working_dir = workspace["working_dir"]

    older_hash = _commit_file(working_dir, "src/older.py", "print('old')\n", "Older commit")
    newer_hash = _commit_file(working_dir, "src/newer.py", "print('new')\n", "Newer commit")

    (Path(working_dir) / "unauthorized").mkdir(exist_ok=True)
    (Path(working_dir) / "unauthorized" / "evil.py").write_text("print('evil')\n")
    _git(working_dir, "add", ".")
    _git(working_dir, "commit", "-m", "Add file outside scope")
    out_of_scope_hash = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=working_dir,
        capture_output=True, text=True,
    ).stdout.strip()

    _git(working_dir, "reset", "--hard", older_hash)

    db = get_db()
    db.execute(
        "UPDATE workspaces SET yolo_mode = 1, last_confirmed_commit = ? WHERE id = ?",
        (newer_hash, workspace["id"])
    )
    db.commit()
    db.close()

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": out_of_scope_hash})

    assert code == 200, result
    assert result["phase"] == "3.2.0"


def test_commit_not_head_is_rejected(workspace, project):
    """A commit hash that exists but is not the current HEAD is rejected."""
    _setup_execution_phase(workspace["id"], "3.1.4")
    add_progress(workspace["id"], "3.1", "Sub-phase 1 complete")

    working_dir = workspace["working_dir"]
    older_hash = _commit_file(working_dir, "src/first.py", "print('a')\n", "First")
    _commit_file(working_dir, "src/second.py", "print('b')\n", "Second")

    ws = _get_ws_row(workspace["id"])
    result, code = perform_advance(ws, project["path"], body={"commit_hash": older_hash})

    assert code == 422
    assert "not the current HEAD" in result["message"]


def test_lazy_init_on_entering_execution_start_sets_head(workspace, project):
    """Transitioning INTO a phase matching ``^3\\.\\d+\\.0$`` with NULL
    ``last_confirmed_commit`` records the current HEAD as the checkpoint so
    the first commit submitted at 3.N.4 has a concrete base."""
    from advance.orchestrator import transition_phase

    _setup_execution_phase(workspace["id"], "2.0")

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workspace["working_dir"],
        capture_output=True, text=True,
    ).stdout.strip()

    assert _last_confirmed_commit(workspace["id"]) is None

    ws = _get_ws_row(workspace["id"])
    db = get_db()
    ok = transition_phase(db, ws, "3.1.0")
    db.commit()
    db.close()

    assert ok is True
    assert _last_confirmed_commit(workspace["id"]) == head
