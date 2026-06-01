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

_FETCH_TIMEOUT_S = 30


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
    """Return the files that should be reviewed in a diff <base_ref>...<head_ref>.

    Runs `git diff --find-renames --name-status base...head` under repo_path,
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


def get_branch_diff(repo_path: Path, base_ref: str, head_ref: str = "HEAD") -> str:
    """Branch diff vs base: a --stat overview followed by the full unified diff.

    Three-dot (merge-base) semantics. Empty string on any git failure.
    """
    stat = _run_git_text(repo_path, ["git", "diff", "--find-renames", "--stat", f"{base_ref}...{head_ref}"])
    patch = _run_git_text(repo_path, ["git", "diff", "--find-renames", f"{base_ref}...{head_ref}"])
    sections = []
    if stat.strip():
        sections.append("Summary:\n" + stat.strip())
    if patch.strip():
        sections.append("Diff:\n" + patch.strip())
    return "\n\n".join(sections)


def resolve_review_base(repo_path: Path, base_ref: str) -> str:
    """Resolve the diff base for review, preferring a freshly-fetched remote branch.

    Feature branches are cut from origin/<base>, but the local <base> ref is
    typically stale in worktree setups — it is never pulled, so diffing against
    it drags in every ticket merged since the branch was cut and inflates the
    reviewable-file count. Fetch origin/<base> best-effort and prefer it; fall
    back to the given ref when there is no remote (offline / local-only repos)
    so a diff is still produced.
    """
    if "/" in base_ref:
        return base_ref
    _fetch_quietly(repo_path, base_ref)
    remote_ref = f"origin/{base_ref}"
    if _ref_exists(repo_path, remote_ref):
        return remote_ref
    return base_ref


def _fetch_quietly(repo_path: Path, branch: str) -> None:
    try:
        subprocess.run(
            ["git", "fetch", "origin", branch],
            cwd=repo_path, capture_output=True, text=True, timeout=_FETCH_TIMEOUT_S,
        )
    except Exception:  # noqa: BLE001 - fetch is best-effort; a stale origin still beats local
        pass


def _ref_exists(repo_path: Path, ref: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=repo_path, capture_output=True, text=True,
        )
    except Exception:  # noqa: BLE001 - bad/missing repo path → treat ref as absent
        return False
    return result.returncode == 0


def _run_git_diff(repo_path: Path, base_ref: str, head_ref: str) -> str:
    result = subprocess.run(
        ["git", "diff", "--find-renames", "--name-status", f"{base_ref}...{head_ref}"],
        cwd=repo_path, check=True, capture_output=True, text=True,
    )
    return result.stdout


def _run_git_text(repo_path: Path, argv: list[str]) -> str:
    try:
        result = subprocess.run(
            argv, cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:  # noqa: BLE001 - best-effort; missing diff degrades gracefully
        return ""


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
