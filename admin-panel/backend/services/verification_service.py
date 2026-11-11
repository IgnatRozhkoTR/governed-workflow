"""Verification profile management and execution service."""
import subprocess
import time
from datetime import datetime
from pathlib import Path


def _load_profile_with_steps(db, profile):
    """Return profile as dict with its steps appended."""
    result = dict(profile)
    result["steps"] = [dict(r) for r in db.execute(
        "SELECT * FROM verification_steps WHERE profile_id = ? ORDER BY sort_order",
        (result["id"],)
    ).fetchall()]
    return result


def _load_run_with_steps(db, run):
    """Return verification run as dict with its step results appended."""
    result = dict(run)
    result["steps"] = [dict(r) for r in db.execute(
        "SELECT * FROM verification_step_results WHERE run_id = ?", (run["id"],)
    ).fetchall()]
    return result


def get_all_profiles(db):
    """Get all verification profiles with their steps."""
    profiles = [dict(r) for r in db.execute(
        "SELECT * FROM verification_profiles ORDER BY origin, name"
    ).fetchall()]
    return [_load_profile_with_steps(db, p) for p in profiles]


def get_profile(db, profile_id):
    """Get a single profile with steps."""
    row = db.execute("SELECT * FROM verification_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        return None
    return _load_profile_with_steps(db, row)


def create_profile(db, name, language, description=None):
    """Create a new user verification profile."""
    now = datetime.now().isoformat()
    cursor = db.execute(
        "INSERT INTO verification_profiles (name, language, description, origin, created_at) "
        "VALUES (?, ?, ?, 'user', ?)",
        (name.strip(), language.strip(), description.strip() if description else None, now)
    )
    return {"ok": True, "id": cursor.lastrowid}


def update_profile_description(db, profile_id, description):
    """Replace the description of an existing verification profile; blank clears it."""
    row = db.execute("SELECT id FROM verification_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        return {"error": "profile_not_found"}
    db.execute(
        "UPDATE verification_profiles SET description = ? WHERE id = ?",
        (description.strip() or None, profile_id),
    )
    return {"ok": True}


def delete_profile(db, profile_id):
    """Delete a verification profile. Cascade deletes handle steps and assignments."""
    row = db.execute("SELECT id, name FROM verification_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        return None
    db.execute("DELETE FROM verification_profiles WHERE id = ?", (profile_id,))
    return dict(row)


def add_step(db, profile_id, name, command, description=None, install_check_command=None,
             install_command=None, enabled=True, sort_order=0, timeout=120, fail_severity="blocking"):
    """Add a verification step to a profile."""
    profile = db.execute("SELECT id FROM verification_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not profile:
        return {"error": "profile_not_found"}
    now = datetime.now().isoformat()
    cursor = db.execute(
        "INSERT INTO verification_steps (profile_id, name, description, command, install_check_command, "
        "install_command, enabled, sort_order, timeout, fail_severity, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (profile_id, name.strip(), description.strip() if description else None, command.strip(),
         install_check_command.strip() if install_check_command else None,
         install_command.strip() if install_command else None,
         1 if enabled else 0, sort_order, timeout, fail_severity, now)
    )
    return {"ok": True, "id": cursor.lastrowid}


def update_step(db, step_id, **kwargs):
    """Update a verification step's fields."""
    row = db.execute("SELECT * FROM verification_steps WHERE id = ?", (step_id,)).fetchone()
    if not row:
        return {"error": "step_not_found"}

    allowed = {"name", "description", "command", "install_check_command", "install_command",
               "enabled", "sort_order", "timeout", "fail_severity"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return {"error": "nothing_to_update"}

    if "enabled" in updates:
        updates["enabled"] = 1 if updates["enabled"] else 0

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [step_id]
    db.execute(f"UPDATE verification_steps SET {set_clause} WHERE id = ?", values)
    return {"ok": True}


def delete_step(db, step_id):
    """Delete a verification step."""
    row = db.execute("SELECT id FROM verification_steps WHERE id = ?", (step_id,)).fetchone()
    if not row:
        return {"error": "step_not_found"}
    db.execute("DELETE FROM verification_steps WHERE id = ?", (step_id,))
    return {"ok": True}


def get_project_profiles(db, project_id):
    """Get profiles assigned to a project."""
    rows = db.execute(
        "SELECT pp.id as assignment_id, pp.subpath, vp.* FROM project_verification_profiles pp "
        "JOIN verification_profiles vp ON pp.profile_id = vp.id "
        "WHERE pp.project_id = ? ORDER BY vp.name",
        (project_id,)
    ).fetchall()
    result = []
    for r in rows:
        result.append(_load_profile_with_steps(db, r))
    return result


def assign_profile(db, project_id, profile_id, subpath="."):
    """Assign a profile to a project."""
    profile = db.execute("SELECT id FROM verification_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not profile:
        return {"error": "profile_not_found"}
    existing = db.execute(
        "SELECT id FROM project_verification_profiles WHERE project_id = ? AND profile_id = ? AND subpath = ?",
        (project_id, profile_id, subpath)
    ).fetchone()
    if existing:
        return {"error": "already_assigned"}
    cursor = db.execute(
        "INSERT INTO project_verification_profiles (project_id, profile_id, subpath) VALUES (?, ?, ?)",
        (project_id, profile_id, subpath)
    )
    return {"ok": True, "id": cursor.lastrowid}


def unassign_profile(db, assignment_id, project_id):
    """Remove a profile assignment from a project."""
    row = db.execute(
        "SELECT id FROM project_verification_profiles WHERE id = ? AND project_id = ?",
        (assignment_id, project_id)
    ).fetchone()
    if not row:
        return {"error": "assignment_not_found"}
    db.execute("DELETE FROM project_verification_profiles WHERE id = ?", (assignment_id,))
    return {"ok": True}


def _get_project_id_for_workspace(db, workspace_id):
    """Look up the project_id for a given workspace."""
    row = db.execute("SELECT project_id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    return row["project_id"] if row else None


def run_verification(db, workspace_id, phase, working_dir):
    """Run all assigned verification profiles for a workspace. Returns (passed, run_id).

    Every write is committed immediately so no SQLite write lock is held while
    shell steps execute; other connections stay free to write during a long run.
    """
    assignments = _load_assignments(db, workspace_id)
    if not assignments:
        return True, None

    run_id = _start_run(db, workspace_id, phase)
    try:
        all_passed = _run_assignments(db, run_id, assignments, working_dir)
    except BaseException:
        db.rollback()
        _finish_run(db, run_id, "failed")
        raise
    _finish_run(db, run_id, "passed" if all_passed else "failed")
    return all_passed, run_id


def _load_assignments(db, workspace_id):
    """Return the profile assignments of the workspace's project."""
    project_id = _get_project_id_for_workspace(db, workspace_id)
    if not project_id:
        return []
    return db.execute(
        "SELECT pp.subpath, vp.id as profile_id, vp.name as profile_name "
        "FROM project_verification_profiles pp "
        "JOIN verification_profiles vp ON pp.profile_id = vp.id "
        "WHERE pp.project_id = ?",
        (project_id,)
    ).fetchall()


def _start_run(db, workspace_id, phase):
    """Insert and commit a 'running' verification run; return its id."""
    cursor = db.execute(
        "INSERT INTO verification_runs (workspace_id, phase, status, started_at) VALUES (?, ?, 'running', ?)",
        (workspace_id, phase, datetime.now().isoformat())
    )
    db.commit()
    return cursor.lastrowid


def _finish_run(db, run_id, status):
    """Commit the final status and completion time of a verification run."""
    db.execute(
        "UPDATE verification_runs SET status = ?, completed_at = ? WHERE id = ?",
        (status, datetime.now().isoformat(), run_id)
    )
    db.commit()


def _run_assignments(db, run_id, assignments, working_dir):
    """Run the enabled steps of every assigned profile; return whether all blocking steps passed."""
    all_passed = True
    for assignment in assignments:
        subpath = assignment["subpath"]
        step_dir = str(Path(working_dir) / subpath) if subpath != "." else working_dir
        steps = db.execute(
            "SELECT * FROM verification_steps WHERE profile_id = ? AND enabled = 1 ORDER BY sort_order",
            (assignment["profile_id"],)
        ).fetchall()
        for step in steps:
            status = _run_and_record_step(db, run_id, step, assignment["profile_name"], step_dir)
            if status == "failed":
                all_passed = False
    return all_passed


def _run_and_record_step(db, run_id, step, profile_name, step_dir):
    """Execute one step, commit its result row, and return its status."""
    start_time = time.time()
    status, output = _execute_step(step, step_dir)
    duration_ms = int((time.time() - start_time) * 1000)
    db.execute(
        "INSERT INTO verification_step_results (run_id, step_name, profile_name, status, output, duration_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, step["name"], profile_name, status, output.strip(), duration_ms)
    )
    db.commit()
    return status


def _execute_step(step, step_dir):
    """Ensure the step's tool is available, then run its command; return (status, output)."""
    try:
        skip_reason, install_note = _prepare_tool(step, step_dir)
        if skip_reason:
            return "skipped", skip_reason
        return _run_step_command(step, step_dir, install_note)
    except subprocess.TimeoutExpired as e:
        return _failure_status(step), f"Timed out after {e.timeout}s"
    except OSError as e:
        return _failure_status(step), f"Error: {e}"


def _prepare_tool(step, step_dir):
    """Run the install check and, if needed, the install. Return (skip_reason, install_note)."""
    if not step["install_check_command"]:
        return None, ""
    if _shell(step["install_check_command"], step_dir, timeout=10).returncode == 0:
        return None, ""
    if not step["install_command"]:
        return (f"Tool not found (check: {step['install_check_command']}), "
                "no install command configured."), ""
    install_result = _shell(step["install_command"], step_dir, timeout=300)
    if install_result.returncode != 0:
        return f"Install failed: {install_result.stderr.strip()}", ""
    return None, "Tool installed. "


def _run_step_command(step, step_dir, output_prefix):
    """Run the step's main command; return (status, output)."""
    timeout = step["timeout"] if step["timeout"] > 0 else None
    result = _shell(step["command"], step_dir, timeout=timeout)
    if result.returncode != 0:
        return _failure_status(step), output_prefix + result.stdout.strip() + "\n" + result.stderr.strip()
    return "passed", output_prefix + result.stdout.strip()


def _failure_status(step):
    """Status recorded for a failing step: 'failed' when blocking, otherwise 'warning'."""
    return "warning" if step["fail_severity"] == "warning" else "failed"


def _shell(command, cwd, timeout):
    """Run a shell command capturing text output."""
    return subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def get_verification_results(db, workspace_id, phase=None, run_id=None):
    """Get verification run results."""
    if run_id:
        run = db.execute(
            "SELECT * FROM verification_runs WHERE id = ? AND workspace_id = ?",
            (run_id, workspace_id)
        ).fetchone()
        if not run:
            return None
        return _load_run_with_steps(db, run)

    query = "SELECT * FROM verification_runs WHERE workspace_id = ?"
    params = [workspace_id]
    if phase:
        query += " AND phase = ?"
        params.append(phase)
    query += " ORDER BY started_at DESC LIMIT 1"

    run = db.execute(query, params).fetchone()
    if not run:
        return None
    return _load_run_with_steps(db, run)


