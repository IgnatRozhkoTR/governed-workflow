"""Filter a git diff into a reviewable file list, excluding noise.

Excluded:
  - Pure renames (status R100 — no content delta; integration reviewers see the move holistically via the full diff).
  - Generated / vendor patterns: */migrations/*.py, *.min.js, *.min.css, */vendor/*,
    *_pb.py, *.snap, *.lock, package-lock.json, yarn.lock.
  - Partial renames (R<100) ARE included.

Used by ReviewPipelineService to compute the fan-out list of per-file reviewers
and the count for the pre-flight gate.
"""

from __future__ import annotations
import fnmatch
import subprocess
from dataclasses import dataclass
from pathlib import Path

GENERATED_PATTERNS: tuple[str, ...] = (
    "*/migrations/*.py",
    "*.min.js",
    "*.min.css",
    "*/vendor/*",
    "*_pb.py",
    "*.snap",
    "*.lock",
    # fnmatch's * matches path separators, so these cover nested paths too:
    # e.g. "frontend/package-lock.json" matches "*package-lock.json"
    "*package-lock.json",
    "*yarn.lock",
)


@dataclass(frozen=True)
class ReviewableFile:
    path: str           # post-change path (for renames, the NEW path)
    status: str         # M (modified), A (added), D (deleted), R<NN> (rename), etc.
    similarity: int | None = None  # for renames: similarity percent (R100 = pure rename, R85 = 85% similar)


def list_reviewable_files(
    repo_path: Path,
    base_ref: str,
    head_ref: str = "HEAD",
    extra_excludes: tuple[str, ...] = (),
) -> list[ReviewableFile]:
    """Return the files that should be reviewed in a diff <base_ref>..<head_ref>.

    Runs `git diff --find-renames --name-status base..head` under repo_path,
    parses each line, applies the exclusion rules, returns the survivors.

    extra_excludes: per-project glob patterns to add to GENERATED_PATTERNS for this call.
    """
    raw = _run_git_diff(repo_path, base_ref, head_ref)
    files: list[ReviewableFile] = []
    excludes = GENERATED_PATTERNS + tuple(extra_excludes)
    for line in raw.splitlines():
        rf = _parse_line(line)
        if rf is None:
            continue
        if rf.status == "R100":  # pure rename — skip
            continue
        if rf.status == "D":  # deleted — file no longer exists on disk
            continue
        if _is_excluded(rf.path, excludes):
            continue
        files.append(rf)
    return files


def count_modified(repo_path: Path, base_ref: str, head_ref: str = "HEAD",
                   extra_excludes: tuple[str, ...] = ()) -> int:
    """Convenience for the pre-flight gate — same filter, just the count."""
    return len(list_reviewable_files(repo_path, base_ref, head_ref, extra_excludes))


def _run_git_diff(repo_path: Path, base_ref: str, head_ref: str) -> str:
    result = subprocess.run(
        ["git", "diff", "--find-renames", "--name-status", f"{base_ref}..{head_ref}"],
        cwd=repo_path, check=True, capture_output=True, text=True,
    )
    return result.stdout


def _parse_line(line: str) -> ReviewableFile | None:
    """Parse one --name-status line.

    Formats:
      'M\\tpath/to/file.py'              -> modified
      'A\\tpath/to/file.py'              -> added
      'D\\tpath/to/file.py'              -> deleted
      'R100\\told/path\\tnew/path'       -> pure rename (100% similar)
      'R085\\told/path\\tnew/path'       -> partial rename (85% similar)
    """
    parts = line.split("\t")
    if len(parts) < 2:
        return None
    status = parts[0]
    if status.startswith("R") and len(parts) >= 3:
        try:
            similarity = int(status[1:]) if len(status) > 1 else None
        except ValueError:
            similarity = None
        return ReviewableFile(path=parts[2], status=status, similarity=similarity)
    # M/A/D and similar single-path entries
    return ReviewableFile(path=parts[1], status=status)


def _is_excluded(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)
