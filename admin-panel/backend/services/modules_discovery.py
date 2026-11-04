"""Shared helpers for multi-root module directory discovery and override resolution."""
import sqlite3
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


def enabled_module_ids(db: sqlite3.Connection) -> list[str]:
    """Return enabled module ids ordered by ``enabled_at`` then ``module_id`` (ascending).

    This is the deterministic precedence order for override application: a
    module enabled later — or, on a tie, alphabetically later — wins any
    relative-path collision against another enabled module's override.
    """
    rows = db.execute(
        "SELECT module_id FROM modules_enabled ORDER BY enabled_at ASC, module_id ASC"
    ).fetchall()
    return [row["module_id"] for row in rows]


def resolve_enabled_module_overrides(
    db: sqlite3.Connection, subpath: str, roots: list[Path]
) -> dict[str, Path]:
    """Return ``{relative_path: source_path}`` for enabled modules' ``override/<subpath>/`` trees.

    Each enabled module's directory is resolved via :func:`iter_module_dirs` over
    *roots* (so a ``modules-local`` copy shadows the tracked one), then scanned
    recursively for files under ``override/<subpath>/``. Modules are applied in
    ascending ``(enabled_at, module_id)`` order — see
    :func:`enabled_module_ids` — so a later-enabled module's file wins
    on a relative-path collision with an earlier one.

    A module with no ``override/<subpath>/`` directory, or one not present under
    any root, contributes nothing; this is the normal case.
    """
    module_dirs_by_id = {entry.name: entry for entry in iter_module_dirs(roots)}
    composed: dict[str, Path] = {}
    for module_id in enabled_module_ids(db):
        module_dir = module_dirs_by_id.get(module_id)
        if module_dir is None:
            continue
        override_root = module_dir / "override" / subpath
        if not override_root.is_dir():
            continue
        for src_file in sorted(override_root.rglob("*")):
            if src_file.is_file():
                composed[str(src_file.relative_to(override_root))] = src_file
    return composed
