"""Helper functions for workspace operations."""
import json
import os
import re
import subprocess
from pathlib import Path

VALID_CRITERIA_TYPES = ("unit_test", "integration_test", "bdd_scenario", "custom")
DEFAULT_SOURCE_BRANCH = "develop"


def compute_phase_sequence(plan, enabled_phases: set | None = None):
    """Derive phase sequence from plan, filtered by enabled_phases if provided.

    enabled_phases: optional set of phase IDs that are enabled. When None, all phases
    are returned (legacy behavior). When provided, phases not in the set are filtered out.

    Module-contributed DeclarativePhase instances are spliced in by band: preparation
    phases appear after the static 1.x-2.x block; finalization phases appear before
    the static 4.x-5 block. Ordering within each band is driven by the phase's
    integer ``position`` attribute.
    """
    fixed_before = ["0", "1.0", "1.1", "1.2", "1.3", "1.4", "2.0", "2.1"]
    fixed_after = ["4.0", "4.1", "4.2", "5"]

    execution = plan.get("execution", []) if isinstance(plan, dict) else []
    exec_phases = []
    if execution:
        for item in execution:
            item_id = item.get("id", "")
            n = item_id.split(".")[-1] if "." in item_id else item_id
            for k in range(5):
                exec_phases.append(f"3.{n}.{k}")

    module_prep, module_final = _module_phases_by_band()
    full = fixed_before + module_prep + exec_phases + module_final + fixed_after

    if enabled_phases is None:
        return full
    return [p for p in full if p in enabled_phases]


# Lazy import inside function: core/ is a leaf layer and must not take a
# top-level dependency on advance/. The advance.phases module imports this
# module at startup, so a top-level import would form a cycle.
def _module_phases_by_band():
    """Return (preparation_ids, finalization_ids) for module-contributed phases.

    Each list is sorted by the declared position. Execution- and planning-band
    modules are not supported and are filtered out upstream by the loader.
    """
    try:
        from advance.phases import PHASE_REGISTRY
        from advance.phases.declarative import DeclarativePhase
    except ImportError:
        return [], []

    prep = sorted(
        (p for p in PHASE_REGISTRY.values()
         if isinstance(p, DeclarativePhase) and p.band == "preparation"),
        key=lambda p: p.position,
    )
    final = sorted(
        (p for p in PHASE_REGISTRY.values()
         if isinstance(p, DeclarativePhase) and p.band == "finalization"),
        key=lambda p: p.position,
    )
    return [p.id for p in prep], [p.id for p in final]


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
    result = subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30
    )
    return result.returncode == 0, result.stdout, result.stderr


def find_workspace(db, project_id, branch):
    sanitized = sanitize_branch(branch)
    return db.execute(
        "SELECT * FROM workspaces WHERE project_id = ? AND sanitized_branch = ?",
        (project_id, sanitized)
    ).fetchone()
