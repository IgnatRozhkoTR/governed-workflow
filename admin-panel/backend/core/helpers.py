"""Helper functions for workspace operations."""
import json
import os
import re
import subprocess
from pathlib import Path

from core.phase import is_templated, phase_key

VALID_CRITERIA_TYPES = ("unit_test", "integration_test", "bdd_scenario", "custom")
DEFAULT_SOURCE_BRANCH = "develop"


def _expand_template(template_id: str, execution: list[dict]) -> list[str]:
    """Expand a single-wildcard templated id against every execution item.

    The execution-item id (e.g. ``"3.2"``) replaces the ``x`` segment so that
    ``"3.x.0"`` paired with items ``["3.1", "3.2"]`` yields ``["3.1.0", "3.2.0"]``.
    Items missing a usable numeric component are skipped rather than raising so
    that a malformed plan cannot collapse the sequencer.
    """
    segments = template_id.split(".")
    expanded: list[str] = []
    for item in execution:
        item_id = item.get("id", "")
        numeric = item_id.split(".")[-1] if "." in item_id else item_id
        if not numeric:
            continue
        concrete = ".".join(numeric if seg == "x" else seg for seg in segments)
        expanded.append(concrete)
    return expanded


def compute_phase_sequence(
    plan,
    enabled_phases: set | None = None,
    registered_phase_ids: list[str] | None = None,
):
    """Derive the ordered phase sequence for the given plan.

    ``registered_phase_ids`` is the complete universe of phase ids the caller
    wants considered — typically ``list(PHASE_REGISTRY.keys())``. Templated ids
    (any segment equal to ``"x"``) are expanded against ``plan["execution"]``
    items. The resulting ids are sorted by ``phase_key`` and filtered through
    ``enabled_phases`` when provided.

    Core stays at the leaf layer by accepting the registry view from callers
    rather than importing from ``advance`` or ``services``. When
    ``registered_phase_ids`` is ``None`` the function returns an empty list so
    missing injection is loud rather than producing a misleading partial
    sequence.
    """
    if registered_phase_ids is None:
        return []

    execution = plan.get("execution", []) if isinstance(plan, dict) else []

    all_ids: list[str] = []
    for phase_id in registered_phase_ids:
        if is_templated(phase_id):
            all_ids.extend(_expand_template(phase_id, execution))
        else:
            all_ids.append(phase_id)

    unique_sorted = sorted(set(all_ids), key=phase_key)
    if enabled_phases is None:
        return unique_sorted
    return [p for p in unique_sorted if p in enabled_phases]


def match_scope_pattern(filepath, pattern):
    """Match a file path against a scope pattern supporting ** globs."""
    pattern = pattern.rstrip("/")
    parts = re.escape(pattern).replace(r"\*\*", "DOUBLESTAR").replace(r"\*", "[^/]*").replace("DOUBLESTAR", ".*")
    regex = "^" + parts + "(/.*)?$"
    return bool(re.match(regex, filepath))


def sanitize_branch(branch):
    return re.sub(r'[^a-zA-Z0-9._-]', '-', branch)


def workspace_dir(project_path, branch):
    return Path(project_path) / ".claude" / "workspaces" / sanitize_branch(branch)


def read_json(path, default=None):
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return default if default is not None else {}


def write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def run_git(cwd, *args):
    """Invoke ``git`` in ``cwd`` and return ``(ok, stdout, stderr)``.

    ``errors="replace"`` keeps non-utf8 diff bytes (latin-1 text files, stray
    bytes in a file) from crashing the caller — they become U+FFFD markers in
    the returned string instead of raising ``UnicodeDecodeError``.

    A missing or non-directory ``cwd`` (stale worktree) surfaces as
    ``FileNotFoundError`` / ``NotADirectoryError`` from ``subprocess.run``; we
    map those to ``(False, "", <message>)`` so every caller treats them like
    any other git failure instead of propagating an unhandled exception.
    """
    return run_git_with(cwd, list(args))


def run_git_with(cwd, args, env_overrides=None, stdin_input=None):
    """Invoke ``git`` with optional env overrides and stdin, return ``(ok, stdout, stderr)``.

    ``env_overrides`` is merged onto the current process environment so callers
    can set ``GIT_AUTHOR_*`` when replaying commits with ``commit-tree`` and
    still preserve the existing git config. ``stdin_input`` feeds a string to
    git's stdin (used for ``commit-tree -F -`` so commit messages with newlines
    and shell-special characters are passed verbatim, never interpolated).

    Shares the same failure mapping as ``run_git`` so callers treat a stale
    worktree (``FileNotFoundError`` / ``NotADirectoryError``) like any other git
    failure instead of propagating an unhandled exception.
    """
    env = None
    if env_overrides:
        env = {**os.environ, **env_overrides}
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            errors="replace",
            env=env,
            input=stdin_input,
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        return False, "", f"working directory unavailable: {exc}"
    return result.returncode == 0, result.stdout, result.stderr


def find_workspace(db, project_id, branch):
    sanitized = sanitize_branch(branch)
    return db.execute(
        "SELECT * FROM workspaces WHERE project_id = ? AND sanitized_branch = ?",
        (project_id, sanitized)
    ).fetchone()
