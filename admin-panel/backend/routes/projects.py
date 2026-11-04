"""Project CRUD routes."""
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from core.db import get_db
from core.decorators import with_project
from core.helpers import run_git, write_json
from core.i18n import t
from core.paths import DEFAULT_GIT_RULES
from services import lsp_service
from services.advance_mode_service import seed_default_modes
from services.configurator_service import ConfiguratorChain
from services.project_settings_service import (
    ProjectSettingsError,
    get_fast_mode_default,
    get_review_mode_default,
    get_simple_planning,
    set_fast_mode_default,
    set_review_mode_default,
    set_simple_planning,
)
from services.repo_service import UNSET, get_repo, list_repos, scan_repos, set_repos, update_repo

log = logging.getLogger(__name__)

bp = Blueprint("projects", __name__)

_VALID_PROJECT_TYPES = frozenset({"single", "multi"})


@bp.route("/api/projects", methods=["GET"])
def list_projects():
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, name, path, registered, project_type FROM projects ORDER BY registered"
        ).fetchall()
        projects = [dict(row) for row in rows]
        return jsonify({"projects": projects})
    finally:
        db.close()


@bp.route("/api/projects", methods=["POST"])
def register_project():
    body = request.get_json(silent=True) or {}
    path = body.get("path", "").strip()
    name = body.get("name", "").strip()
    project_type = body.get("project_type") or "single"

    if project_type not in _VALID_PROJECT_TYPES:
        return jsonify({"error": t("api.error.invalidProjectType")}), 400

    if not path or not os.path.isdir(path):
        return jsonify({"error": t("api.error.invalidDirectoryPath")}), 400

    if project_type == "single":
        ok, _, _ = run_git(path, "rev-parse", "--git-dir")
        if not ok:
            run_git(path, "init")
            run_git(path, "checkout", "-b", "develop")
            gitignore = Path(path) / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text("")
            run_git(path, "add", ".gitignore")
            run_git(path, "commit", "-m", "Initial commit")

    if not name:
        name = os.path.basename(path)

    project_id = re.sub(r'[^a-zA-Z0-9_-]', '-', name.lower())

    db = get_db()
    try:
        existing = db.execute("SELECT id, name, path, registered FROM projects WHERE path = ?", (path,)).fetchone()
        if existing:
            return jsonify({"error": t("api.error.projectAlreadyRegistered"), "project": dict(existing)}), 409

        registered = datetime.now().isoformat()
        db.execute(
            "INSERT INTO projects (id, name, path, registered, project_type) VALUES (?, ?, ?, ?, ?)",
            (project_id, name, path, registered, project_type)
        )
        seed_default_modes(db, project_id)

        _setup_project_configs(path)
        warnings = []
        try:
            results = ConfiguratorChain.default().run(db, project_id, Path(path))
            warnings = [r for r in results if r["action"] != "rendered"]
        except Exception:
            log.exception("Configurator chain failed at register_project; SKILL.md may be stale")

        project = {
            "id": project_id, "name": name, "path": path, "registered": registered,
            "project_type": project_type,
        }
        if warnings:
            project["configurator_warnings"] = warnings
        return jsonify(project), 201
    finally:
        db.close()


def _setup_project_configs(project_path):
    provider, host = _detect_git_provider(project_path)

    git_config_path = Path(project_path) / ".claude" / "git-config.json"
    if not git_config_path.exists():
        write_json(git_config_path, {
            "provider": provider,
            "host": host,
            "token": "",
            "default_branch": "develop",
        })

    if provider == "gitlab" and host:
        mcp_path = Path(project_path) / ".mcp.json"
        if not mcp_path.exists():
            write_json(mcp_path, {
                "mcpServers": {
                    "gitlab": {
                        "command": "npx",
                        "args": ["-y", "@zereight/mcp-gitlab"],
                        "env": {
                            "GITLAB_PERSONAL_ACCESS_TOKEN": "",
                            "GITLAB_API_URL": f"https://{host}/api/v4",
                        },
                    }
                }
            })

    _ensure_git_rules_symlink(project_path)


def _detect_git_provider(project_path):
    ok, stdout, _ = run_git(project_path, "remote", "get-url", "origin")
    if not ok or not stdout.strip():
        return "local", ""

    remote_url = stdout.strip()

    if "gitlab" in remote_url:
        host = _extract_host(remote_url)
        return "gitlab", host

    if "github" in remote_url:
        host = _extract_host(remote_url)
        return "github", host

    return "local", ""


def _extract_host(remote_url):
    if remote_url.startswith("http://") or remote_url.startswith("https://"):
        return urlparse(remote_url).hostname or ""
    if remote_url.startswith("git@"):
        match = re.match(r"git@([^:]+):", remote_url)
        return match.group(1) if match else ""
    return ""


def _ensure_git_rules_symlink(project_path):
    rules_path = Path(project_path) / ".claude" / "git-rules.md"
    if rules_path.exists() or rules_path.is_symlink():
        return

    system_default = DEFAULT_GIT_RULES
    if not system_default.exists():
        return

    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.symlink_to(system_default)


@bp.route("/api/projects/<project_id>/settings", methods=["GET"])
@with_project
def get_project_settings(db, project):
    return jsonify({
        "simple_planning": get_simple_planning(db, project["id"]),
        "fast_mode_default": get_fast_mode_default(db, project["id"]),
        "review_mode_default": get_review_mode_default(db, project["id"]),
        "project_type": project["project_type"],
    })


@bp.route("/api/projects/<project_id>/settings", methods=["PUT"])
@with_project
def put_project_settings(db, project):
    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify({"error": "at least one of simple_planning, fast_mode_default, review_mode_default is required"}), 400

    simple_planning = body.get("simple_planning")
    if simple_planning is not None and not isinstance(simple_planning, bool):
        return jsonify({"error": "simple_planning must be a boolean"}), 400

    fast_mode_default = body.get("fast_mode_default")
    if fast_mode_default is not None and not isinstance(fast_mode_default, bool):
        return jsonify({"error": "fast_mode_default must be a boolean"}), 400

    review_mode_default = body.get("review_mode_default")
    if review_mode_default is not None and not isinstance(review_mode_default, str):
        return jsonify({"error": "review_mode_default must be a string"}), 400

    try:
        if simple_planning is not None:
            set_simple_planning(db, project["id"], simple_planning)
        if fast_mode_default is not None:
            set_fast_mode_default(db, project["id"], fast_mode_default)
        if review_mode_default is not None:
            set_review_mode_default(db, project["id"], review_mode_default)
        db.commit()
    except ProjectSettingsError as exc:
        status = 404 if exc.code == "project_not_found" else 400
        return jsonify({"error": str(exc)}), status

    warnings = []
    try:
        results = ConfiguratorChain.default().run(db, project["id"], Path(project["path"]))
        warnings = [r for r in results if r["action"] != "rendered"]
    except Exception:
        log.exception("Configurator chain failed at put_project_settings; SKILL.md may be stale")

    response = {
        "ok": True,
        "simple_planning": get_simple_planning(db, project["id"]),
        "fast_mode_default": get_fast_mode_default(db, project["id"]),
        "review_mode_default": get_review_mode_default(db, project["id"]),
    }
    if warnings:
        response["configurator_warnings"] = warnings
    return jsonify(response)


@bp.route("/api/projects/<project_id>/repo-scan", methods=["GET"])
@with_project
def repo_scan(db, project):
    return jsonify({"candidates": scan_repos(project["path"])})


@bp.route("/api/projects/<project_id>/convert-multi", methods=["POST"])
@with_project
def convert_multi(db, project):
    body = request.get_json(silent=True) or {}
    repos = body.get("repos")
    if not isinstance(repos, list) or not repos:
        return jsonify({"error": t("api.error.reposRequired")}), 400

    candidates = {c["rel_path"] for c in scan_repos(project["path"])}
    selected = []
    for entry in repos:
        rel_path = entry.get("rel_path", "").strip() if isinstance(entry, dict) else ""
        if not rel_path:
            return jsonify({"error": t("api.error.invalidRepoSelection")}), 400
        if Path(rel_path).is_absolute() or ".." in Path(rel_path).parts:
            return jsonify({"error": t("api.error.invalidRepoSelection")}), 400
        if rel_path not in candidates:
            return jsonify({"error": t("api.error.invalidRepoSelection")}), 400
        base_branch = entry.get("base_branch") or "develop"
        selected.append({"rel_path": rel_path, "base_branch": base_branch})

    db.execute("UPDATE projects SET project_type = 'multi' WHERE id = ?", (project["id"],))
    set_repos(db, project["id"], selected)

    return jsonify({"project_type": "multi", "repos": list_repos(db, project["id"])})


@bp.route("/api/projects/<project_id>/repos", methods=["GET"])
@with_project
def get_project_repos(db, project):
    return jsonify({"project_type": project["project_type"], "repos": list_repos(db, project["id"])})


@bp.route("/api/projects/<project_id>/repos/<int:repo_id>", methods=["GET"])
@with_project
def get_project_repo(db, project, repo_id):
    repo = get_repo(db, project["id"], repo_id)
    if repo is None:
        return jsonify({"error": t("api.error.repoNotFound")}), 404
    return jsonify(repo)


@bp.route("/api/projects/<project_id>/repos/<int:repo_id>", methods=["PUT"])
@with_project
def put_project_repo(db, project, repo_id):
    body = request.get_json(silent=True) or {}
    has_base_branch = "base_branch" in body
    has_override = "git_rules_override" in body
    if not has_base_branch and not has_override:
        return jsonify({"error": t("api.error.repoUpdateBodyRequired")}), 400

    base_branch = None
    if has_base_branch:
        base_branch = body.get("base_branch")
        if not isinstance(base_branch, str) or not base_branch.strip():
            return jsonify({"error": t("api.error.invalidBaseBranch")}), 400

    git_rules_override = UNSET
    if has_override:
        git_rules_override = body.get("git_rules_override")
        if git_rules_override is not None and not isinstance(git_rules_override, str):
            return jsonify({"error": t("api.error.invalidGitRulesOverride")}), 400

    existing = get_repo(db, project["id"], repo_id)
    if existing is None:
        return jsonify({"error": t("api.error.repoNotFound")}), 404

    updated = update_repo(
        db, project["id"], repo_id, base_branch=base_branch, git_rules_override=git_rules_override
    )
    return jsonify(updated)


@bp.route("/api/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    db = get_db()
    try:
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        db.commit()
        try:
            lsp_service.remove_lsp_cache_dirs(project_id)
        except Exception:
            log.exception("Failed to clean up LSP cache dirs for project=%s", project_id)
        return jsonify({"ok": True})
    finally:
        db.close()
