"""Shared helper for multi-root module directory discovery."""
from pathlib import Path


def iter_module_dirs(roots: list[Path], required_file: str = "SKILL.md") -> list[Path]:
    """Return a deduplicated, order-preserving list of module directories.

    For each root in order, scan subdirectories that contain *required_file*. When a
    module-id (directory name) appears in more than one root, the LATER root wins
    (local root shadows tracked root). Subdirectories without *required_file* are skipped.

    Args:
        roots: Ordered list of root directories to scan. Later roots shadow earlier ones.
        required_file: Filename that must exist in a subdirectory for it to be included.
            Defaults to ``"SKILL.md"`` for skill discovery. Pass ``"phase.yaml"`` to
            discover modules that contribute phases.
    """
    by_id: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and (entry / required_file).is_file():
                by_id[entry.name] = entry  # later roots overwrite earlier
    return [by_id[k] for k in sorted(by_id.keys())]
