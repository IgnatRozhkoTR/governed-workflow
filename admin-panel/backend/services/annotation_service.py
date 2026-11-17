"""Code annotations: short explanatory notes attached to a file's line range.

Annotations are context for readers, not review comments: they have no
replies, no resolution and never block a gate. Each one stores the exact text
of its lines at creation (``anchor_text``) and is re-anchored on read against
whatever version of the file is being displayed (see
:mod:`services.annotation_anchor`). Shared by ``routes/annotations.py`` (HTTP),
``mcp_tools/annotations.py`` (MCP) and the review pipeline. Callers own the
transaction: write functions never commit.
"""
from datetime import datetime
from pathlib import Path, PurePosixPath

from core.helpers import run_git
from core.i18n import t
from routes.files import _resolve_repo_dir, read_file_bytes_at_ref
from services.annotation_anchor import (
    AnchorPosition,
    capture_anchor,
    is_valid_range,
    resolve_anchor,
    split_lines,
)

PRIMARY_REPO = ""

_MESSAGE_KEYS = {
    "text_required": "api.error.annotationTextRequired",
    "line_numbers_invalid": "api.error.annotationLineNumbersInvalid",
    "invalid_line_range": "api.error.annotationLineRangeOutsideFile",
    "invalid_file_path": "api.error.annotationInvalidFilePath",
    "file_not_found": "api.error.fileNotFound",
    "not_found": "api.error.annotationNotFound",
    "nothing_to_update": "api.error.annotationNothingToUpdate",
    "repo_required": "api.error.repoRequired",
    "repo_not_found": "api.error.repoNotFound",
    "invalid_repo": "api.error.invalidRepo",
    "invalid_ref": "api.error.invalidRef",
    "base_ref_not_found": "api.error.refNotFound",
}

_COLUMNS = (
    "id, repo, file_path, line_start, line_end, text, author, anchor_text, created_at, updated_at"
)


class AnnotationServiceError(Exception):
    """Domain error carrying a stable ``code`` and the params of its i18n message."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params

    def message(self, locale: str = "en") -> str:
        return t(_MESSAGE_KEYS[self.code], locale, **self.params)


def create_annotation(db, ws, project, *, repo: str, file_path: str, line_start, line_end,
                      text: str, author: str) -> dict:
    repo = normalize_repo(repo)
    file_path = _normalize_file_path(file_path)
    text = _validated_text(text)
    repo_dir = _repo_dir(db, ws, project, repo)
    lines = _working_tree_lines(repo_dir, file_path)
    _validate_range(lines, line_start, line_end)
    now = datetime.now().isoformat()
    cursor = db.execute(
        "INSERT INTO annotations (workspace_id, repo, file_path, line_start, line_end, text, author, "
        "anchor_text, base_commit, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ws["id"], repo, file_path, line_start, line_end, text, author,
         capture_anchor(lines, line_start, line_end), _head_commit(repo_dir), now, now),
    )
    return _stored_view(_require_row(db, ws["id"], cursor.lastrowid))


def update_annotation(db, ws, project, annotation_id: int, *, text=None, line_start=None,
                      line_end=None) -> dict:
    """Change the text and/or the line range; a new range recaptures the anchor from the working tree."""
    if text is None and line_start is None and line_end is None:
        raise AnnotationServiceError("nothing_to_update")
    row = _require_row(db, ws["id"], annotation_id)
    changes = {} if text is None else {"text": _validated_text(text)}
    if line_start is not None or line_end is not None:
        changes.update(_recaptured_anchor(
            db, ws, project, row,
            row["line_start"] if line_start is None else line_start,
            row["line_end"] if line_end is None else line_end,
        ))
    changes["updated_at"] = datetime.now().isoformat()
    assignments = ", ".join(f"{column} = ?" for column in changes)
    db.execute(f"UPDATE annotations SET {assignments} WHERE id = ?", (*changes.values(), annotation_id))
    return _stored_view(_require_row(db, ws["id"], annotation_id))


def delete_annotation(db, workspace_id: int, annotation_id: int) -> None:
    deleted = db.execute(
        "DELETE FROM annotations WHERE id = ? AND workspace_id = ?", (annotation_id, workspace_id)
    ).rowcount
    if deleted == 0:
        raise AnnotationServiceError("not_found", annotation_id=annotation_id)


def delete_workspace_annotations(db, workspace_id: int) -> None:
    db.execute("DELETE FROM annotations WHERE workspace_id = ?", (workspace_id,))


def list_annotations(db, workspace_id: int) -> list[dict]:
    """All of the workspace's annotations at their stored lines, without re-anchoring."""
    rows = db.execute(
        f"SELECT {_COLUMNS} FROM annotations WHERE workspace_id = ? "
        "ORDER BY repo, file_path, line_start, id",
        (workspace_id,),
    ).fetchall()
    return [_stored_view(row) for row in rows]


def list_file_annotations(db, ws, project, *, repo: str, file_path: str, ref: str | None = None) -> list[dict]:
    """Annotations of one file, re-anchored against the working tree or, when ``ref`` is given, that ref's content."""
    repo = normalize_repo(repo)
    file_path = _normalize_file_path(file_path)
    repo_dir = _repo_dir(db, ws, project, repo)
    lines = _lines_at_ref(repo_dir, ref, file_path) if ref else _working_tree_lines(repo_dir, file_path)
    return annotations_for_lines(db, ws["id"], repo, file_path, lines)


def annotations_for_lines(db, workspace_id: int, repo: str, file_path: str, lines: list[str]) -> list[dict]:
    """Re-anchor one file's annotations against the given file lines."""
    rows = db.execute(
        f"SELECT {_COLUMNS} FROM annotations WHERE workspace_id = ? AND repo = ? AND file_path = ? "
        "ORDER BY line_start, id",
        (workspace_id, repo, file_path),
    ).fetchall()
    resolved = [_view(row, resolve_anchor(lines, row["line_start"], row["line_end"], row["anchor_text"]))
                for row in rows]
    return sorted(resolved, key=lambda annotation: (annotation["line_start"], annotation["id"]))


def normalize_repo(repo: str | None) -> str:
    repo = (repo or "").strip()
    return PRIMARY_REPO if repo == "." else repo


def _recaptured_anchor(db, ws, project, row, line_start, line_end) -> dict:
    repo_dir = _repo_dir(db, ws, project, row["repo"])
    lines = _working_tree_lines(repo_dir, row["file_path"])
    _validate_range(lines, line_start, line_end)
    return {
        "line_start": line_start,
        "line_end": line_end,
        "anchor_text": capture_anchor(lines, line_start, line_end),
        "base_commit": _head_commit(repo_dir),
    }


def _require_row(db, workspace_id: int, annotation_id: int):
    row = db.execute(
        f"SELECT {_COLUMNS} FROM annotations WHERE id = ? AND workspace_id = ?",
        (annotation_id, workspace_id),
    ).fetchone()
    if row is None:
        raise AnnotationServiceError("not_found", annotation_id=annotation_id)
    return row


def _normalize_file_path(file_path: str | None) -> str:
    raw = (file_path or "").strip()
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or path.as_posix() == ".":
        raise AnnotationServiceError("invalid_file_path", file_path=raw)
    return path.as_posix()


def _validated_text(text) -> str:
    if not isinstance(text, str) or not text.strip():
        raise AnnotationServiceError("text_required")
    return text.strip()


def _validate_range(lines: list[str], line_start, line_end) -> None:
    if not _is_line_number(line_start) or not _is_line_number(line_end):
        raise AnnotationServiceError("line_numbers_invalid")
    if not is_valid_range(lines, line_start, line_end):
        raise AnnotationServiceError(
            "invalid_line_range", line_start=line_start, line_end=line_end, total_lines=len(lines)
        )


def _is_line_number(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _repo_dir(db, ws, project, repo: str) -> Path:
    working_dir, error_code = _resolve_repo_dir(db, ws, project, repo)
    if error_code:
        raise AnnotationServiceError(error_code, repo=repo)
    return Path(working_dir)


def _working_tree_lines(repo_dir: Path, file_path: str) -> list[str]:
    root = repo_dir.resolve()
    absolute_path = (root / file_path).resolve()
    if not absolute_path.is_relative_to(root):
        raise AnnotationServiceError("invalid_file_path", file_path=file_path)
    if not absolute_path.is_file():
        raise AnnotationServiceError("file_not_found", file_path=file_path)
    return split_lines(absolute_path.read_bytes().decode("utf-8", errors="replace"))


def _lines_at_ref(repo_dir: Path, ref: str, file_path: str) -> list[str]:
    content, error_code = read_file_bytes_at_ref(str(repo_dir), ref, file_path)
    if error_code:
        raise AnnotationServiceError(error_code, ref=ref, file_path=file_path)
    return split_lines(content.decode("utf-8", errors="replace"))


def _head_commit(repo_dir: Path) -> str | None:
    """HEAD at annotation time; informational only, so an unborn or broken HEAD is recorded as NULL."""
    ok, stdout, _ = run_git(str(repo_dir), "rev-parse", "HEAD")
    return stdout.strip() if ok else None


def _stored_view(row) -> dict:
    return _view(row, AnchorPosition(row["line_start"], row["line_end"], False))


def _view(row, position: AnchorPosition) -> dict:
    return {
        "id": row["id"],
        "repo": row["repo"],
        "file_path": row["file_path"],
        "line_start": position.line_start,
        "line_end": position.line_end,
        "text": row["text"],
        "author": row["author"],
        "stale": position.stale,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
