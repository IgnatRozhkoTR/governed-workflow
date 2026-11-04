"""File read and diff routes."""
import logging
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

from core.decorators import with_workspace
from core.helpers import run_git, DEFAULT_SOURCE_BRANCH
from core.i18n import t
from services import repo_service

logger = logging.getLogger(__name__)

bp = Blueprint("files", __name__)


def _is_within(path: Path, root: Path) -> bool:
    """Return True if path is within root (both resolved)."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _has_git_marker(path: Path) -> bool:
    """Return True if path contains a .git entry (dir for a normal repo, file for a worktree)."""
    git_entry = path / ".git"
    return git_entry.is_dir() or git_entry.is_file()


def _resolve_multi_repo_dir(db, workspace_id: int, repo_param: str) -> tuple[str | None, str | None]:
    """Resolve a repo param to its attached worktree_path for a multi-repo workspace.

    There is no workspace-root repo in multi-repo mode, so an empty/"." param
    is a required-parameter error rather than falling back to any directory.
    """
    if not repo_param or repo_param == ".":
        return None, "repo_required"

    attached = repo_service.list_attached(db, workspace_id)
    match = next((row for row in attached if row["rel_path"] == repo_param), None)
    if match is None:
        return None, "repo_not_found"

    worktree_path = Path(match["worktree_path"])
    if not worktree_path.is_dir():
        return None, "repo_not_found"

    return str(worktree_path), None


def _resolve_single_repo_dir(working_dir: str, project_path: str, repo_param: str) -> tuple[str | None, str | None]:
    """Resolve an optional inner-repository subpath to an absolute directory.

    "." (or omitted) means the workspace working_dir itself. Any other value is
    resolved against the project path, since inner repositories only ever exist
    there (the working_dir may be a worktree that only contains the parent
    repo's tracked files).
    """
    if not repo_param or repo_param == ".":
        return str(Path(working_dir)), None

    if Path(repo_param).is_absolute() or ".." in Path(repo_param).parts:
        return None, "invalid_repo"

    root = Path(project_path).resolve()
    candidate = (root / repo_param).resolve()
    if not _is_within(candidate, root):
        return None, "invalid_repo"

    if not candidate.is_dir() or not _has_git_marker(candidate):
        return None, "repo_not_found"

    return str(candidate), None


def _resolve_repo_dir(db, ws, project, repo_param: str) -> tuple[str | None, str | None]:
    """Resolve an optional inner-repository subpath to an absolute directory.

    Branches on the project's type: multi-repo projects only ever resolve
    against their attached workspace_repos/worktree_path rows, never against
    the shared project-root checkout; single-repo projects keep the legacy
    project-path subdirectory scan.
    """
    if project["project_type"] == "multi":
        return _resolve_multi_repo_dir(db, ws["id"], repo_param)
    return _resolve_single_repo_dir(ws["working_dir"], project["path"], repo_param)


@bp.route("/api/ws/<project_id>/<path:branch>/file", methods=["GET"])
@with_workspace
def read_file(db, ws, project):
    working_dir = ws["working_dir"]

    rel_path = request.args.get("path", "")
    start_line = request.args.get("start", type=int)
    end_line = request.args.get("end", type=int)
    absolute = request.args.get("absolute", "").lower() in ("true", "1")

    if not rel_path:
        return jsonify({"error": t("api.error.pathRequired")}), 400

    if absolute:
        file_path = Path(rel_path).resolve()
        allowed_roots = [Path(working_dir).resolve()]
        allowed_external = ws["allowed_external_paths"] if ws["allowed_external_paths"] else ""
        for ext_path in (p.strip() for p in allowed_external.split(",") if p.strip()):
            allowed_roots.append(Path(ext_path).resolve())
        if not any(_is_within(file_path, root) for root in allowed_roots):
            return jsonify({"error": t("api.error.pathOutsideWorkingDir")}), 403
    else:
        file_path = Path(working_dir) / rel_path
        try:
            file_path.resolve().relative_to(Path(working_dir).resolve())
        except ValueError:
            return jsonify({"error": t("api.error.pathOutsideWorkingDir")}), 403

    if not file_path.exists():
        return jsonify({"error": t("api.error.fileNotFound")}), 404

    try:
        lines = file_path.read_text().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return jsonify({"error": str(e)}), 500

    if start_line is not None and end_line is not None:
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)
        context_before = max(0, start_idx - 5)
        context_after = min(len(lines), end_idx + 5)
        selected_lines = lines[context_before:context_after]
        return jsonify({
            "path": rel_path,
            "start": context_before + 1,
            "end": context_after,
            "highlight_start": start_line,
            "highlight_end": end_line,
            "lines": selected_lines,
            "total_lines": len(lines)
        })

    return jsonify({
        "path": rel_path,
        "lines": lines,
        "total_lines": len(lines)
    })


@bp.route("/api/ws/<project_id>/<path:branch>/file", methods=["PUT"])
@with_workspace
def write_file(db, ws, project):
    working_dir = ws["working_dir"]
    body = request.get_json(silent=True) or {}

    rel_path = body.get("path", "")
    if not rel_path:
        return jsonify({"error": t("api.error.pathRequired")}), 400

    file_path = Path(working_dir) / rel_path
    try:
        file_path.resolve().relative_to(Path(working_dir).resolve())
    except ValueError:
        return jsonify({"error": t("api.error.pathOutsideWorkingDir")}), 403

    content = body.get("content", "")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return jsonify({"ok": True})


def _collapse_single_dirs(entries, all_files):
    """Collapse chains of directories that contain only a single subdirectory."""
    result = []
    for entry in entries:
        if entry["type"] != "dir":
            result.append(entry)
            continue

        dir_path = entry["path"]
        display_name = entry["name"]

        while True:
            prefix = dir_path + "/"
            children = {}
            for f in all_files:
                if not f.startswith(prefix):
                    continue
                relative = f[len(prefix):]
                first_part = relative.split("/")[0]
                is_dir = "/" in relative
                if first_part not in children:
                    children[first_part] = is_dir

            dir_children = {k: v for k, v in children.items() if v}
            file_children = {k: v for k, v in children.items() if not v}

            if len(dir_children) == 1 and len(file_children) == 0:
                only_child = list(dir_children.keys())[0]
                display_name += "/" + only_child
                dir_path = dir_path + "/" + only_child
            else:
                break

        result.append({"name": display_name, "type": "dir", "path": dir_path})
    return result


@bp.route("/api/ws/<project_id>/<path:branch>/files", methods=["GET"])
@with_workspace
def list_files(db, ws, project):
    """List directory entries lazily. Returns one level of entries at a time."""
    working_dir = ws["working_dir"]

    dir_path = request.args.get("path", "")
    search = request.args.get("search", "").strip().lower()

    ok_tracked, tracked_out, _ = run_git(working_dir, "ls-files")
    if not ok_tracked:
        return jsonify({"error": t("api.error.failedToListFiles")}), 500

    ok_others, others_out, _ = run_git(working_dir, "ls-files", "--others", "--exclude-standard")
    tracked = [f for f in tracked_out.strip().split("\n") if f]
    others = [f for f in others_out.strip().split("\n") if f] if ok_others else []
    seen = set(tracked)
    all_files = tracked + [f for f in others if f not in seen]

    if search:
        matched = [f for f in all_files if search in f.split("/")[-1].lower()]
        return jsonify({"entries": [{"name": f, "path": f, "type": "file"} for f in matched[:200]]})

    if dir_path:
        prefix = dir_path.rstrip("/") + "/"
        children_files = [f for f in all_files if f.startswith(prefix)]
    else:
        prefix = ""
        children_files = all_files

    entries = {}
    for f in children_files:
        relative = f[len(prefix):]
        first_part = relative.split("/")[0]
        is_dir = "/" in relative
        if first_part not in entries:
            entries[first_part] = {"name": first_part, "type": "dir" if is_dir else "file", "path": (prefix + first_part) if is_dir else f}

    sorted_entries = sorted(entries.values(), key=lambda e: (0 if e["type"] == "dir" else 1, e["name"].lower()))
    sorted_entries = _collapse_single_dirs(sorted_entries, all_files)

    result = {"entries": sorted_entries}
    if not dir_path:
        result["total"] = len(all_files)
    return jsonify(result)


@bp.route("/api/ws/<project_id>/<path:branch>/repos", methods=["GET"])
@with_workspace
def get_repos(db, ws, project):
    """List the repositories available for diffing in this workspace.

    Multi-repo projects only ever expose their attached repos (no workspace-root
    entry, since the composite workspace directory is not itself a git repo).
    Single-repo projects keep the legacy workspace root plus any immediate
    subdirectory of the project path that is a git repository.
    """
    if project["project_type"] == "multi":
        attached = repo_service.list_attached(db, ws["id"])
        repos = [{"path": row["rel_path"], "name": row["name"] or row["rel_path"]} for row in attached]
        return jsonify({"repos": repos})

    root = Path(project["path"])

    repos = [{"path": ".", "name": Path(project["path"]).name}]

    if not root.is_dir():
        return jsonify({"repos": repos})

    subdirs = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if not entry.is_dir():
                    continue
                if entry.name.startswith(".") or entry.name == "node_modules":
                    continue
                if _has_git_marker(Path(entry.path)):
                    subdirs.append(entry.name)
    except OSError:
        return jsonify({"repos": repos})

    for name in sorted(subdirs):
        repos.append({"path": name, "name": name})

    return jsonify({"repos": repos})


_LOG_FORMAT = "%H%x00%h%x00%s%x00%an%x00%ae%x00%aI%x00%b%x1e"


def _parse_log(raw, ahead_shas):
    commits = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split("\x00", 6)
        if len(parts) < 6:
            continue
        full_sha = parts[0]
        sha = parts[1]
        subject = parts[2]
        author_name = parts[3]
        author_email = parts[4]
        author_date = parts[5]
        body = parts[6].strip() if len(parts) > 6 else ""
        commits.append({
            "sha": sha,
            "full_sha": full_sha,
            "subject": subject,
            "body": body,
            "author_name": author_name,
            "author_email": author_email,
            "author_date": author_date,
            "ahead_of_origin": full_sha in ahead_shas,
        })
    return commits


def _ahead_shas(working_dir, ref):
    ok, out, _ = run_git(working_dir, "log", "--pretty=format:%H", f"{ref}..HEAD")
    if not ok:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def _try_history_refs(working_dir, source_branch, log_format):
    """Try candidate ref expressions in order; return (raw_log, ahead_shas_set) for the first success."""
    candidates = [
        f"origin/{source_branch}..HEAD",
        f"{source_branch}..HEAD",
        None,
    ]
    for ref_expr in candidates:
        if ref_expr is not None:
            ok, raw, _ = run_git(working_dir, "log", "--abbrev=12", f"--format={log_format}", ref_expr)
            if ok:
                ahead = _ahead_shas(working_dir, ref_expr.split("..")[0])
                return raw, ahead
        else:
            ok, raw, _ = run_git(working_dir, "log", "--abbrev=12", f"--format={log_format}", "--max-count=200")
            if not ok:
                return "", set()
            ok_rev, out_rev, _ = run_git(working_dir, "rev-list", "--max-count=200", "HEAD")
            all_shas = {line.strip() for line in out_rev.splitlines() if line.strip()} if ok_rev else set()
            return raw, all_shas
    return "", set()


@bp.route("/api/ws/<project_id>/<path:branch>/history", methods=["GET"])
@with_workspace
def get_history(db, ws, project):
    repo = request.args.get("repo", "").strip()
    working_dir, err = _resolve_repo_dir(db, ws, project, repo)
    if err:
        return jsonify({"error": err}), 400

    ref_param = request.args.get("ref")
    if ref_param:
        ok, raw, _ = run_git(working_dir, "log", "--abbrev=12", f"--format={_LOG_FORMAT}", "--max-count=50", ref_param)
        if not ok:
            return jsonify({"commits": [], "source_branch": ref_param})
        commits = _parse_log(raw, set())
        return jsonify({"commits": commits, "source_branch": ref_param, "browsing": True})

    source_branch = ws["source_branch"] or DEFAULT_SOURCE_BRANCH
    raw, ahead = _try_history_refs(working_dir, source_branch, _LOG_FORMAT)
    commits = _parse_log(raw, ahead)
    return jsonify({"commits": commits, "source_branch": source_branch})


@bp.route("/api/ws/<project_id>/<path:branch>/branches", methods=["GET"])
@with_workspace
def get_branches(db, ws, project):
    repo = request.args.get("repo", "").strip()
    working_dir, err = _resolve_repo_dir(db, ws, project, repo)
    if err:
        return jsonify({"error": err}), 400

    ok, out, _ = run_git(working_dir, "branch", "-a", "--sort=-committerdate", "--format=%(refname:short)")
    if not ok:
        return jsonify({"branches": []})

    current_branch = ws["branch"] or ""
    branches = []
    seen = set()
    for line in out.splitlines():
        name = line.strip()
        if not name or name == "HEAD" or "HEAD ->" in name:
            continue
        display_name = name
        if name.startswith("origin/"):
            display_name = name[7:]
            if display_name == "HEAD":
                continue
        if display_name in seen:
            continue
        seen.add(display_name)
        branches.append({
            "name": display_name,
            "ref": name,
            "current": display_name == current_branch,
        })
    return jsonify({"branches": branches})


def _diff_for_commit(working_dir, sha):
    """Validate sha and return parsed diff files list, or an error tuple."""
    if not sha:
        return jsonify({"error": "commit query parameter is required for mode=commit"}), 400

    ok_cat, _, _ = run_git(working_dir, "cat-file", "-e", f"{sha}^{{commit}}")
    if not ok_cat:
        return jsonify({"error": "commit not found"}), 404

    ok_anc, _, _ = run_git(working_dir, "merge-base", "--is-ancestor", sha, "HEAD")
    if not ok_anc:
        return jsonify({"error": "commit is not an ancestor of HEAD"}), 400

    ok, diff_output, _ = run_git(working_dir, "show", "--format=", "--patch", "--find-renames", sha)
    return _parse_diff(diff_output if ok else "")


def _resolve_explicit_base_ref(working_dir, base_override):
    """Return the first ref (origin/<base> then <base>) that verifies as a commit, or None."""
    for ref in (f"origin/{base_override}", base_override):
        ok, _, _ = run_git(working_dir, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if ok:
            return ref
    return None


def _diff_for_branch(working_dir, source_branch, base_override=None):
    """Return diff output against the source branch, or an explicit base ref if provided.

    Returns None when base_override was given but no matching ref could be verified,
    to distinguish that failure from a genuinely empty diff ("").
    """
    if base_override:
        ref = _resolve_explicit_base_ref(working_dir, base_override)
        if ref is None:
            return None
        ok, diff_output, _ = run_git(working_dir, "diff", "--find-renames", ref)
        return diff_output if ok else ""

    for ref in (f"origin/{source_branch}", source_branch, "HEAD", None):
        if ref is not None:
            ok, diff_output, _ = run_git(working_dir, "diff", "--find-renames", ref)
        else:
            ok, diff_output, _ = run_git(working_dir, "diff", "--find-renames")
        if ok:
            return diff_output
    return ""


def _untracked_files_diff(working_dir, mode, tracked_paths):
    """Return synthetic diff entries for untracked (new) files not already in tracked_paths."""
    new_paths = set()
    ok_ls, ls_out, _ = run_git(working_dir, "ls-files", "--others", "--exclude-standard")
    if ok_ls:
        new_paths.update(line.strip() for line in ls_out.splitlines() if line.strip())

    if mode == "branch":
        # Also include staged new files not yet in the tracked diff
        ok_cached, cached_out, _ = run_git(working_dir, "diff", "--cached", "--name-only")
        if ok_cached:
            new_paths.update(line.strip() for line in cached_out.splitlines() if line.strip())

    entries = []
    for rel_path in new_paths:
        if rel_path in tracked_paths:
            continue
        file_path = Path(working_dir) / rel_path
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        content_lines = content.splitlines()
        diff_lines = [
            f"diff --git a/{rel_path} b/{rel_path}",
            "new file mode 100644",
            "--- /dev/null",
            f"+++ b/{rel_path}",
            f"@@ -0,0 +1,{len(content_lines)} @@",
        ] + ["+" + l for l in content_lines]
        entries.append({
            "path": rel_path,
            "old_path": None,
            "similarity": None,
            "additions": len(content_lines),
            "deletions": 0,
            "diff": "\n".join(diff_lines),
            "status": "new",
        })
    return entries


@bp.route("/api/ws/<project_id>/<path:branch>/diff", methods=["GET"])
@with_workspace
def get_diff(db, ws, project):
    working_dir = ws["working_dir"]
    source_branch = ws["source_branch"] or DEFAULT_SOURCE_BRANCH

    mode = request.args.get("mode", "branch")
    if mode not in ("branch", "uncommitted", "commit"):
        return jsonify({"error": f"unknown mode '{mode}', expected: branch, uncommitted, commit"}), 400

    if not Path(working_dir).is_dir():
        return jsonify({
            "error": "working_dir_unavailable",
            "details": f"workspace directory does not exist: {working_dir}",
        }), 400

    repo = request.args.get("repo", "").strip()
    working_dir, err = _resolve_repo_dir(db, ws, project, repo)
    if err:
        return jsonify({"error": err}), 400

    base = request.args.get("base", "").strip()

    try:
        if mode == "commit":
            sha = request.args.get("commit", "").strip()
            result = _diff_for_commit(working_dir, sha)
            if isinstance(result, tuple):
                return result
            return jsonify({"files": result, "mode": "commit", "commit": sha})

        if mode == "branch":
            diff_output = _diff_for_branch(working_dir, source_branch, base_override=base or None)
            if diff_output is None:
                return jsonify({"error": "base_ref_not_found", "base": base}), 400
        else:
            ok, diff_output, _ = run_git(working_dir, "diff", "--find-renames", "HEAD")
            if not ok:
                diff_output = ""

        files = _parse_diff(diff_output)
        files.extend(_untracked_files_diff(working_dir, mode, {f["path"] for f in files}))

        response = {"files": files, "mode": mode}
        if mode == "branch":
            response["base"] = base or source_branch
        return jsonify(response)
    except Exception as exc:
        logger.exception(
            "diff handler failed for %s/%s mode=%s",
            project["id"], ws["branch"], mode,
        )
        return jsonify({"error": "diff_failed", "details": str(exc)}), 500


def _parse_diff(diff_output):
    """Parse unified diff output into a list of file entries, detecting renames."""
    files = []
    if not diff_output or not diff_output.strip():
        return files

    current_file = None
    current_old_file = None
    current_similarity = None
    current_diff_lines = []

    for line in diff_output.split("\n"):
        if line.startswith("diff --git"):
            if current_file:
                files.append({
                    "path": current_file,
                    "old_path": current_old_file,
                    "similarity": current_similarity,
                    "additions": sum(1 for l in current_diff_lines if l.startswith("+") and not l.startswith("+++")),
                    "deletions": sum(1 for l in current_diff_lines if l.startswith("-") and not l.startswith("---")),
                    "diff": "\n".join(current_diff_lines)
                })
            parts = line.split(" b/", 1)
            current_file = parts[1] if len(parts) > 1 else ""
            current_old_file = None
            current_similarity = None
            current_diff_lines = [line]
        elif current_file is not None:
            current_diff_lines.append(line)
            if line.startswith("similarity index"):
                similarity_str = line.split("similarity index ")[1].rstrip("%") if " " in line else ""
                try:
                    current_similarity = int(similarity_str)
                except ValueError:
                    current_similarity = None
            elif line.startswith("rename from "):
                current_old_file = line.split("rename from ", 1)[1]
            elif line.startswith("--- a/"):
                old_name = line[6:]
                if not current_old_file and old_name != current_file:
                    current_old_file = old_name

    if current_file:
        files.append({
            "path": current_file,
            "old_path": current_old_file,
            "similarity": current_similarity,
            "additions": sum(1 for l in current_diff_lines if l.startswith("+") and not l.startswith("+++")),
            "deletions": sum(1 for l in current_diff_lines if l.startswith("-") and not l.startswith("---")),
            "diff": "\n".join(current_diff_lines)
        })

    return files
