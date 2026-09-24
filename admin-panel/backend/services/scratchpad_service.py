"""Scratchpad markdown report management under ``.claude/scratchpad/``.

Scratchpads are human-facing markdown reports shown in the admin panel's
Scratchpads tab. This module is the single place that resolves the
scratchpad directory for a workspace/repo, validates file names, and
performs create/read/replace/patch/delete on scratchpad files — shared by
``routes/scratchpads.py`` (HTTP) and ``mcp_tools/scratchpad.py`` (MCP).
"""
from datetime import datetime, timezone
from pathlib import Path

from routes.files import _resolve_repo_dir


class ScratchpadServiceError(Exception):
    """Domain error for scratchpad operations, carrying a short error code."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def resolve_scratchpad_dir(db, ws, project, repo_param: str) -> tuple[Path | None, str | None]:
    """Resolve the ``.claude/scratchpad/`` directory for this request.

    Single-repo projects always use the workspace's own working_dir — unlike
    the general file-browser routes, scratchpads do not scope into nested
    inner repos there. Multi-repo projects use the workspace's composite
    working_dir (the parent directory shared by all attached repos) when
    ``repo`` is omitted/".", or defer to files.py's attached-repo resolution
    (and its ``repo_required``/``repo_not_found`` error codes) otherwise.
    """
    if project["project_type"] != "multi" or not repo_param or repo_param == ".":
        return Path(ws["working_dir"]) / ".claude" / "scratchpad", None

    working_dir, err = _resolve_repo_dir(db, ws, project, repo_param)
    if err:
        return None, err
    return Path(working_dir) / ".claude" / "scratchpad", None


def normalize_name(name: str) -> str:
    """Append ``.md`` to a bare filename if the caller omitted it."""
    name = (name or "").strip()
    if name and not name.endswith(".md"):
        name = f"{name}.md"
    return name


def validate_name(name: str) -> str | None:
    """Return an error code if ``name`` is not a safe flat ``.md`` filename."""
    if not name:
        return "invalid_name"
    if not name.endswith(".md"):
        return "invalid_name"
    if "/" in name or ".." in name or Path(name).is_absolute():
        return "invalid_name"
    return None


def iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def title_for(path: Path) -> str:
    try:
        with path.open() as f:
            first_line = f.readline().strip()
    except OSError:
        first_line = ""
    if first_line.startswith("# "):
        return first_line[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").title()


def list_scratchpads(scratchpad_dir: Path) -> list[dict]:
    if not scratchpad_dir.is_dir():
        return []

    files = []
    for entry in scratchpad_dir.iterdir():
        if not entry.is_file() or entry.suffix != ".md":
            continue
        files.append({
            "name": entry.name,
            "title": title_for(entry),
            "updated_at": iso_mtime(entry),
            "size": entry.stat().st_size,
        })

    files.sort(key=lambda f: f["updated_at"], reverse=True)
    return files


def read_scratchpad(scratchpad_dir: Path, name: str) -> dict:
    file_path = scratchpad_dir / name
    if not file_path.is_file():
        raise ScratchpadServiceError(f"Scratchpad '{name}' not found.", code="not_found")
    return {
        "content": file_path.read_text(),
        "name": name,
        "updated_at": iso_mtime(file_path),
    }


def write_scratchpad(scratchpad_dir: Path, name: str, content: str) -> dict:
    """Create or overwrite ``name`` unconditionally (legacy PUT route behaviour)."""
    scratchpad_dir.mkdir(parents=True, exist_ok=True)
    file_path = scratchpad_dir / name
    file_path.write_text(content)
    return {"name": name, "title": title_for(file_path), "updated_at": iso_mtime(file_path)}


def _envelope(scratchpad_dir: Path, name: str) -> dict:
    file_path = scratchpad_dir / name
    return {
        "name": name,
        "path": str(file_path),
        "title": title_for(file_path),
        "updated_at": iso_mtime(file_path),
    }


def create_scratchpad(scratchpad_dir: Path, name: str, content: str) -> dict:
    """Create a new scratchpad file. Fails if one already exists at that name."""
    file_path = scratchpad_dir / name
    if file_path.exists():
        raise ScratchpadServiceError(f"Scratchpad '{name}' already exists.", code="already_exists")
    scratchpad_dir.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return _envelope(scratchpad_dir, name)


def replace_scratchpad(scratchpad_dir: Path, name: str, content: str) -> dict:
    """Overwrite an existing scratchpad file. Fails if it does not exist."""
    file_path = scratchpad_dir / name
    if not file_path.is_file():
        raise ScratchpadServiceError(f"Scratchpad '{name}' not found.", code="not_found")
    file_path.write_text(content)
    return _envelope(scratchpad_dir, name)


def patch_scratchpad(scratchpad_dir: Path, name: str, old_string: str, new_string: str) -> dict:
    """Replace exactly one occurrence of ``old_string`` with ``new_string``.

    Fails if the scratchpad does not exist, if ``old_string`` is not found, or
    if it occurs more than once (the replacement would be ambiguous).
    """
    file_path = scratchpad_dir / name
    if not file_path.is_file():
        raise ScratchpadServiceError(f"Scratchpad '{name}' not found.", code="not_found")

    text = file_path.read_text()
    occurrences = text.count(old_string)
    if occurrences == 0:
        raise ScratchpadServiceError(
            f"old_string not found in scratchpad '{name}'.", code="no_match"
        )
    if occurrences > 1:
        raise ScratchpadServiceError(
            f"old_string occurs {occurrences} times in scratchpad '{name}'; it must be unique.",
            code="ambiguous_match",
        )

    file_path.write_text(text.replace(old_string, new_string, 1))
    return _envelope(scratchpad_dir, name)


def delete_scratchpad(scratchpad_dir: Path, name: str) -> None:
    """Delete an existing scratchpad file. Fails if it does not exist."""
    file_path = scratchpad_dir / name
    if not file_path.is_file():
        raise ScratchpadServiceError(f"Scratchpad '{name}' not found.", code="not_found")
    file_path.unlink()
