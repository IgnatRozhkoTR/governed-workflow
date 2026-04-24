"""Git-rules file management under <project>/.claude/git-rules.md.

The file was previously stored inside <project>/.claude/rules/git-rules.md,
which collided with the rule-listing glob.  It has since been relocated to
<project>/.claude/git-rules.md so the two features don't share a directory.
This module owns the path helpers and the one-shot filesystem migration from
the legacy location.
"""
import logging
import shutil
from pathlib import Path


_LOGGER = logging.getLogger(__name__)


def git_rules_path(project_path) -> Path:
    """Canonical location for a project's git-rules file."""
    return Path(project_path) / ".claude" / "git-rules.md"


def legacy_git_rules_path(project_path) -> Path:
    """Pre-relocation location retained for one-shot migration."""
    return Path(project_path) / ".claude" / "rules" / "git-rules.md"


def migrate_legacy_git_rules(project_path) -> None:
    """Move a legacy <project>/.claude/rules/git-rules.md to its new home.

    Idempotent: if no legacy file exists, or the new file already exists,
    nothing happens.  Failures are logged at warning level but never raised,
    so existing workspaces keep functioning if the filesystem is unexpected.
    """
    legacy = legacy_git_rules_path(project_path)
    target = git_rules_path(project_path)

    if target.exists() or target.is_symlink():
        return
    if not (legacy.exists() or legacy.is_symlink()):
        return

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(target))
    except (OSError, shutil.Error) as exc:
        _LOGGER.warning("Failed to migrate legacy git-rules.md at %s: %s", legacy, exc)
