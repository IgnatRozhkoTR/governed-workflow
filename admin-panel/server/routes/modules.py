"""Modules discovery and enabled-state endpoints."""
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

from core.db import get_db_ctx
from core.paths import DEFAULT_MODULES_DIR, DEFAULT_MODULES_LOCAL_DIR
from services.modules_discovery import iter_module_dirs

bp = Blueprint("modules", __name__)

MODULES_DIR = DEFAULT_MODULES_DIR


def _parse_frontmatter(text):
    """Parse YAML frontmatter between --- markers, return dict of key: value pairs."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}
    result = {}
    for line in lines[1:end]:
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _load_module(directory):
    """Return module info dict for a valid module directory, or None if invalid."""
    skill_path = directory / "SKILL.md"
    if not skill_path.is_file():
        return None
    try:
        content = skill_path.read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter = _parse_frontmatter(content)
    module_id = directory.name
    return {
        "id": module_id,
        "name": frontmatter.get("name", module_id),
        "description": frontmatter.get("description", ""),
        "path": str(directory),
        "has_skill": True,
    }


@bp.route("/api/modules", methods=["GET"])
def list_modules():
    modules = []
    for directory in iter_module_dirs([DEFAULT_MODULES_DIR, DEFAULT_MODULES_LOCAL_DIR]):
        module = _load_module(directory)
        if module is not None:
            modules.append(module)
    return jsonify({"modules": modules})


@bp.route("/api/modules/enabled", methods=["GET"])
def get_enabled_modules():
    with get_db_ctx() as db:
        rows = db.execute("SELECT module_id FROM modules_enabled").fetchall()
        return jsonify({"modules": [row["module_id"] for row in rows]})


@bp.route("/api/modules/enabled", methods=["POST"])
def set_enabled_modules():
    body = request.json or {}
    module_ids = body.get("modules", [])
    with get_db_ctx() as db:
        db.execute("DELETE FROM modules_enabled")
        for module_id in module_ids:
            db.execute(
                "INSERT INTO modules_enabled (module_id) VALUES (?)",
                (module_id,),
            )
        db.commit()
        return jsonify({"status": "saved"})
