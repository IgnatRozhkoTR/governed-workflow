"""Per-workspace workflow mode: ``standard`` vs ``fast``.

Fast mode drops the optional research/review sub-phases for a single
workspace by writing workspace-scope ``phase_settings`` disable rows, which the
phase resolver and advance engine already honor. Standard mode clears those
rows so the workspace falls back to the inherited device/project phase set.
Fast mode still includes the reflection phases (5.1/5.2).
"""
from services import phase_settings
from services.configurator_service import ConfiguratorChain

FAST_DISABLED_PHASE_IDS: tuple = ("1.3", "1.4", "3.x.1", "3.x.3", "4.0")
VALID_MODES = ("standard", "fast")

# 3.x.2 (fix-review) is written implicitly by set_scope_settings whenever 3.x.1
# is disabled, so reverting to standard must clear it alongside the explicit set.
# 5.1/5.2 are legacy disable rows from before fast mode included reflection;
# clearing them on revert keeps older fast workspaces from being stuck with
# stale disable rows even though fast mode no longer writes them.
_FAST_ROW_PHASE_IDS: tuple = FAST_DISABLED_PHASE_IDS + ("3.x.2", "5.1", "5.2")


def _validate_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid workflow mode: {mode!r}")


def _project_flag(project, field: str) -> bool:
    try:
        value = project[field]
    except (KeyError, IndexError):
        return False
    return bool(value)


def resolve_default_mode(project, requested_mode=None) -> str:
    """Resolve the effective creation mode from an explicit request or project default.

    An explicit ``requested_mode`` wins (and is validated). When absent, the
    project's ``fast_mode_default`` flag decides between fast and standard.
    """
    if requested_mode is not None:
        _validate_mode(requested_mode)
        return requested_mode
    return "fast" if _project_flag(project, "fast_mode_default") else "standard"


def apply_mode_phase_settings(db, workspace_id, mode: str) -> None:
    """Write or clear the workspace-scope phase-settings rows for the mode.

    Does not update the ``workflow_mode`` column or re-render — callers own
    those steps so workspace creation can seed rows before its single chain run.
    """
    _validate_mode(mode)
    scope_id = str(workspace_id)
    if mode == "fast":
        phase_settings.set_scope_settings(
            db, "workspace", scope_id, {pid: False for pid in FAST_DISABLED_PHASE_IDS}
        )
    else:
        phase_settings.delete_scope_settings(db, "workspace", scope_id, _FAST_ROW_PHASE_IDS)


def set_workspace_mode(db, project, ws, mode: str) -> None:
    """Switch a workspace's workflow mode and re-render its worktree SKILL.md.

    Persists the mode column, applies the workspace-scope phase-settings rows,
    then re-renders the configurator chain for this worktree only. Raises
    ``ValueError`` on an invalid mode. The caller commits.
    """
    _validate_mode(mode)
    db.execute("UPDATE workspaces SET workflow_mode = ? WHERE id = ?", (mode, ws["id"]))
    apply_mode_phase_settings(db, ws["id"], mode)
    updated = db.execute("SELECT * FROM workspaces WHERE id = ?", (ws["id"],)).fetchone()
    ConfiguratorChain.default().run_for_workspace(db, project, updated)
