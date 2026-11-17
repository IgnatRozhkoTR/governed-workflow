"""Code annotation routes: explanatory notes attached to a file's line range."""
from flask import Blueprint, jsonify, request

from core.decorators import with_workspace
from services import annotation_service

bp = Blueprint("annotations", __name__)

_NOT_FOUND_CODES = frozenset({"not_found", "file_not_found", "repo_not_found"})
_USER_AUTHOR = "user"


def _error_response(exc):
    status = 404 if exc.code in _NOT_FOUND_CODES else 400
    return jsonify({"error": exc.message(), "code": exc.code}), status


@bp.route("/api/ws/<project_id>/<path:branch>/annotations", methods=["GET"])
@with_workspace
def list_annotations(db, ws, project):
    file_path = request.args.get("file", "")
    if not file_path.strip():
        return jsonify({"ok": True, "annotations": annotation_service.list_annotations(db, ws["id"])})
    try:
        annotations = annotation_service.list_file_annotations(
            db, ws, project,
            repo=request.args.get("repo", ""),
            file_path=file_path,
            ref=request.args.get("ref", "").strip() or None,
        )
    except annotation_service.AnnotationServiceError as exc:
        return _error_response(exc)
    return jsonify({"ok": True, "annotations": annotations})


@bp.route("/api/ws/<project_id>/<path:branch>/annotations", methods=["POST"])
@with_workspace
def create_annotation(db, ws, project):
    body = request.get_json(silent=True) or {}
    try:
        annotation = annotation_service.create_annotation(
            db, ws, project,
            repo=body.get("repo", ""),
            file_path=body.get("file_path", ""),
            line_start=body.get("line_start"),
            line_end=body.get("line_end"),
            text=body.get("text", ""),
            author=_USER_AUTHOR,
        )
    except annotation_service.AnnotationServiceError as exc:
        return _error_response(exc)
    db.commit()
    return jsonify({"ok": True, "annotation": annotation}), 201


@bp.route("/api/ws/<project_id>/<path:branch>/annotations/<int:annotation_id>", methods=["PATCH"])
@with_workspace
def update_annotation(db, ws, project, annotation_id):
    body = request.get_json(silent=True) or {}
    try:
        annotation = annotation_service.update_annotation(
            db, ws, project, annotation_id,
            text=body.get("text"),
            line_start=body.get("line_start"),
            line_end=body.get("line_end"),
        )
    except annotation_service.AnnotationServiceError as exc:
        return _error_response(exc)
    db.commit()
    return jsonify({"ok": True, "annotation": annotation})


@bp.route("/api/ws/<project_id>/<path:branch>/annotations/<int:annotation_id>", methods=["DELETE"])
@with_workspace
def delete_annotation(db, ws, project, annotation_id):
    try:
        annotation_service.delete_annotation(db, ws["id"], annotation_id)
    except annotation_service.AnnotationServiceError as exc:
        return _error_response(exc)
    db.commit()
    return jsonify({"ok": True})
