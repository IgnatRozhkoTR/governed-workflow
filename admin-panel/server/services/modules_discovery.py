"""Shared helper for multi-root module directory discovery."""
from pathlib import Path


def iter_module_dirs(roots: list[Path]) -> list[Path]:
    """Return a deduplicated, order-preserving list of module directories.

    For each root in order, scan subdirectories that contain SKILL.md. When a
    module-id (directory name) appears in more than one root, the LATER root wins
    (local root shadows tracked root). Invalid entries (no SKILL.md) are skipped.
    """
    by_id: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                by_id[entry.name] = entry  # later roots overwrite earlier
    return [by_id[k] for k in sorted(by_id.keys())]
