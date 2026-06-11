"""Static file serving."""
import json
from pathlib import Path

from flask import Blueprint, make_response, render_template, send_from_directory

bp = Blueprint("static_files", __name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
_I18N_DIR = TEMPLATES_DIR / "i18n"


@bp.route("/")
def index():
    i18n_path = _I18N_DIR / "en.json"
    i18n_default = json.loads(i18n_path.read_text(encoding="utf-8"))
    resp = make_response(render_template("admin.html", i18n_default=json.dumps(i18n_default)))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/css/<path:filename>")
def css_files(filename):
    return send_from_directory(TEMPLATES_DIR / "css", filename)


@bp.route("/js/<path:filename>")
def js_files(filename):
    return send_from_directory(TEMPLATES_DIR / "js", filename)


@bp.route("/i18n/<path:filename>")
def serve_i18n(filename):
    return send_from_directory(TEMPLATES_DIR / "i18n", filename)


@bp.route("/img/<path:filename>")
def img_files(filename):
    return send_from_directory(TEMPLATES_DIR / "img", filename)
