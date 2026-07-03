"""Tests for major-phase-boundary advance-action file writing in transition_phase."""
import os

import pytest

from advance.orchestrator import transition_phase, _is_major_transition
from core.db import get_db
from services.advance_mode_service import set_modes


# ── Unit: boundary detection ──────────────────────────────────────────────────


def test_is_major_transition_detects_crossing():
    assert _is_major_transition("1.4", "2.0") is True


def test_is_major_transition_sub_phase_only():
    assert _is_major_transition("3.1.0", "3.1.1") is False


def test_is_major_transition_same_major():
    assert _is_major_transition("2.0", "2.1") is False


def test_is_major_transition_bad_input_is_safe():
    assert _is_major_transition("", "2.0") is False
    assert _is_major_transition("1.4", "") is False


# ── Integration helpers ───────────────────────────────────────────────────────


def _make_ws(ws_id, project_id, working_dir, phase, workflow_mode=None):
    ws = {
        "id": ws_id,
        "project_id": project_id,
        "working_dir": working_dir,
        "phase": phase,
        "last_confirmed_commit": None,
    }
    if workflow_mode is not None:
        ws["workflow_mode"] = workflow_mode
    return ws


def _action_file(working_dir):
    return os.path.join(working_dir, ".claude", "state", "pending-advance-action")


def _insert_workspace_and_project(db, ws):
    db.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        (ws["project_id"], "Test Project", ws["working_dir"], "2024-01-01T00:00:00"),
    )
    db.execute(
        "INSERT INTO workspaces (id, project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch, last_confirmed_commit) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)",
        (
            ws["id"],
            ws["project_id"],
            f"feature/test-{ws['id']}",
            f"feature-test-{ws['id']}",
            ws["working_dir"],
            "2024-01-01T00:00:00",
            ws["phase"],
            '{"description":"","systemDiagram":"","execution":[]}',
            "develop",
            ws["last_confirmed_commit"],
        ),
    )
    db.commit()


# ── Integration: file-write behaviour ─────────────────────────────────────────


def test_major_transition_compact_mode_writes_file(tmp_path):
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-compact"

    db = get_db()
    try:
        ws = _make_ws(9001, project_id, working_dir, "1.4")
        _insert_workspace_and_project(db, ws)
        set_modes(db, project_id, {"2": "compact"})

        post_commit = transition_phase(db, ws, "2.0")

        assert post_commit is not None
        db.commit()
        for callback in post_commit:
            callback()
    finally:
        db.close()

    action_file = _action_file(working_dir)
    assert os.path.isfile(action_file), "pending-advance-action file must be written"
    assert open(action_file).read() == "compact"


def test_major_transition_clear_mode_writes_file(tmp_path):
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-clear"

    db = get_db()
    try:
        ws = _make_ws(9002, project_id, working_dir, "2.0")
        _insert_workspace_and_project(db, ws)
        set_modes(db, project_id, {"3.1": "clear"})

        post_commit = transition_phase(db, ws, "3.1.0")

        assert post_commit is not None
        db.commit()
        for callback in post_commit:
            callback()
    finally:
        db.close()

    action_file = _action_file(working_dir)
    assert os.path.isfile(action_file)
    assert open(action_file).read() == "clear"


def test_sub_phase_transition_within_same_n_writes_no_file(tmp_path):
    """3.1.0 → 3.1.2 stays within boundary '3.1'; no advance action file is written."""
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-same-n"

    db = get_db()
    try:
        ws = _make_ws(9003, project_id, working_dir, "3.1.0")
        _insert_workspace_and_project(db, ws)
        set_modes(db, project_id, {"3.1": "clear", "3.x": "compact"})

        post_commit = transition_phase(db, ws, "3.1.2")

        assert post_commit is not None
        db.commit()
        for callback in post_commit:
            callback()
    finally:
        db.close()

    assert not os.path.isfile(_action_file(working_dir))


def test_sub_phase_transition_between_n_writes_file_via_template(tmp_path):
    """3.1.4 → 3.2.0 crosses boundary '3.1' → '3.2'; template '3.x' provides the mode."""
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-template"

    db = get_db()
    try:
        ws = _make_ws(9004, project_id, working_dir, "3.1.4")
        _insert_workspace_and_project(db, ws)
        set_modes(db, project_id, {"3.x": "compact"})

        post_commit = transition_phase(db, ws, "3.2.0")

        assert post_commit is not None
        db.commit()
        for callback in post_commit:
            callback()
    finally:
        db.close()

    action_file = _action_file(working_dir)
    assert os.path.isfile(action_file)
    assert open(action_file).read() == "compact"


def test_sub_phase_transition_between_n_exact_match_wins_over_template(tmp_path):
    """3.2.4 → 3.3.0: explicit '3.3' row beats the '3.x' template."""
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-exact-win"

    db = get_db()
    try:
        ws = _make_ws(9005, project_id, working_dir, "3.2.4")
        _insert_workspace_and_project(db, ws)
        set_modes(db, project_id, {"3.3": "clear", "3.x": "compact"})

        post_commit = transition_phase(db, ws, "3.3.0")

        assert post_commit is not None
        db.commit()
        for callback in post_commit:
            callback()
    finally:
        db.close()

    action_file = _action_file(working_dir)
    assert os.path.isfile(action_file)
    assert open(action_file).read() == "clear"


def test_major_transition_none_mode_writes_no_file(tmp_path):
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-none"

    db = get_db()
    try:
        ws = _make_ws(9006, project_id, working_dir, "3.1.4")
        _insert_workspace_and_project(db, ws)
        set_modes(db, project_id, {"4": "none"})

        post_commit = transition_phase(db, ws, "4.0")

        assert post_commit is not None
        db.commit()
        for callback in post_commit:
            callback()
    finally:
        db.close()

    assert not os.path.isfile(_action_file(working_dir))


def test_fast_workspace_major_transition_compact_mode_writes_no_file(tmp_path):
    """A fast-mode workspace never gets an advance action, even when the project's
    boundary mode is 'compact' — every boundary behaves as mode 'none'.
    """
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-fast-compact"

    db = get_db()
    try:
        ws = _make_ws(9008, project_id, working_dir, "1.4", workflow_mode="fast")
        _insert_workspace_and_project(db, ws)
        set_modes(db, project_id, {"2": "compact"})

        post_commit = transition_phase(db, ws, "2.0")

        assert post_commit is not None
        db.commit()
        for callback in post_commit:
            callback()
    finally:
        db.close()

    assert not os.path.isfile(_action_file(working_dir))


def test_standard_workspace_major_transition_compact_mode_still_writes_file(tmp_path):
    """Control for the fast-mode test above: an otherwise-identical standard
    workspace still writes the pending-advance-action file as before.
    """
    working_dir = str(tmp_path / "repo")
    os.makedirs(working_dir)
    project_id = "proj-standard-compact"

    db = get_db()
    try:
        ws = _make_ws(9009, project_id, working_dir, "1.4", workflow_mode="standard")
        _insert_workspace_and_project(db, ws)
        set_modes(db, project_id, {"2": "compact"})

        post_commit = transition_phase(db, ws, "2.0")

        assert post_commit is not None
        db.commit()
        for callback in post_commit:
            callback()
    finally:
        db.close()

    action_file = _action_file(working_dir)
    assert os.path.isfile(action_file), "pending-advance-action file must be written"
    assert open(action_file).read() == "compact"


def test_missing_working_dir_is_graceful(tmp_path):
    project_id = "proj-missing-dir"
    non_existent_dir = str(tmp_path / "does_not_exist")

    db = get_db()
    try:
        ws = _make_ws(9007, project_id, non_existent_dir, "1.4")
        _insert_workspace_and_project(db, ws)
        set_modes(db, project_id, {"2": "compact"})

        post_commit = transition_phase(db, ws, "2.0")

        assert post_commit is not None
        db.commit()
        for callback in post_commit:
            callback()
    finally:
        db.close()

    assert not os.path.isfile(_action_file(non_existent_dir))
