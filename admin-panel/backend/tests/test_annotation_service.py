"""Service-level tests for services/annotation_service.py against a real git repo."""
from pathlib import Path

import pytest

from core.db import get_db
from core.helpers import find_workspace
from services import annotation_service
from services.annotation_service import AnnotationServiceError
from testing_utils import _git

FILE = "src/app.py"
ORIGINAL = "".join(f"line {n}\n" for n in range(1, 11))


@pytest.fixture
def annotated_repo(workspace, git_repo):
    repo = Path(git_repo)
    (repo / "src").mkdir()
    (repo / FILE).write_text(ORIGINAL)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Add app")
    return repo


@pytest.fixture
def db():
    connection = get_db()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def ctx(db, annotated_repo, workspace, project):
    ws = find_workspace(db, project["id"], workspace["branch"])
    project_row = db.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
    return ws, project_row


def _create(db, ctx, **overrides):
    ws, project = ctx
    params = {"repo": "", "file_path": FILE, "line_start": 3, "line_end": 4,
              "text": "Why this exists", "author": "agent"}
    params.update(overrides)
    return annotation_service.create_annotation(db, ws, project, **params)


def _stored_row(db, annotation_id):
    return db.execute("SELECT * FROM annotations WHERE id = ?", (annotation_id,)).fetchone()


def _head(repo):
    import subprocess
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True, check=True).stdout.strip()


class TestCreateAnnotation:
    def test_create_annotation_should_capture_anchor_text_when_range_valid(self, db, ctx):
        created = _create(db, ctx)

        assert _stored_row(db, created["id"])["anchor_text"] == "line 3\nline 4"

    def test_create_annotation_should_record_head_as_base_commit(self, db, ctx, annotated_repo):
        created = _create(db, ctx)

        assert _stored_row(db, created["id"])["base_commit"] == _head(annotated_repo)

    def test_create_annotation_should_return_stored_view_when_created(self, db, ctx):
        created = _create(db, ctx, text="  Padded note  ")

        assert {k: created[k] for k in ("repo", "file_path", "line_start", "line_end", "text", "author", "stale")} == {
            "repo": "", "file_path": FILE, "line_start": 3, "line_end": 4,
            "text": "Padded note", "author": "agent", "stale": False,
        }

    def test_create_annotation_should_normalize_dot_prefixed_path(self, db, ctx):
        created = _create(db, ctx, file_path="./src/app.py")

        assert created["file_path"] == FILE

    @pytest.mark.parametrize("line_start,line_end", [(0, 1), (5, 4), (9, 11)])
    def test_create_annotation_should_reject_range_outside_file(self, db, ctx, line_start, line_end):
        with pytest.raises(AnnotationServiceError) as exc_info:
            _create(db, ctx, line_start=line_start, line_end=line_end)

        assert exc_info.value.code == "invalid_line_range"

    @pytest.mark.parametrize("line_start", ["3", 3.0, None, True])
    def test_create_annotation_should_reject_non_integer_lines(self, db, ctx, line_start):
        with pytest.raises(AnnotationServiceError) as exc_info:
            _create(db, ctx, line_start=line_start)

        assert exc_info.value.code == "line_numbers_invalid"

    def test_create_annotation_should_reject_missing_file(self, db, ctx):
        with pytest.raises(AnnotationServiceError) as exc_info:
            _create(db, ctx, file_path="src/missing.py")

        assert exc_info.value.code == "file_not_found"

    @pytest.mark.parametrize("file_path", ["../outside.py", "src/../../x.py", "/etc/passwd", "", ".", "   "])
    def test_create_annotation_should_reject_unsafe_paths(self, db, ctx, file_path):
        with pytest.raises(AnnotationServiceError) as exc_info:
            _create(db, ctx, file_path=file_path)

        assert exc_info.value.code == "invalid_file_path"

    def test_create_annotation_should_reject_symlink_escaping_repo(self, db, ctx, annotated_repo, tmp_path):
        outside = tmp_path / "secret.txt"
        outside.write_text("secret\n")
        (annotated_repo / "link.txt").symlink_to(outside)

        with pytest.raises(AnnotationServiceError) as exc_info:
            _create(db, ctx, file_path="link.txt", line_start=1, line_end=1)

        assert exc_info.value.code == "invalid_file_path"

    @pytest.mark.parametrize("text", ["", "   ", None, 42])
    def test_create_annotation_should_reject_empty_text(self, db, ctx, text):
        with pytest.raises(AnnotationServiceError) as exc_info:
            _create(db, ctx, text=text)

        assert exc_info.value.code == "text_required"

    def test_create_annotation_should_not_persist_row_when_validation_fails(self, db, ctx, workspace):
        with pytest.raises(AnnotationServiceError):
            _create(db, ctx, line_end=99)

        assert annotation_service.list_annotations(db, workspace["id"]) == []


class TestListFileAnnotations:
    def test_list_file_annotations_should_reanchor_when_working_tree_has_uncommitted_insert(
            self, db, ctx, annotated_repo):
        ws, project = ctx
        _create(db, ctx)
        (annotated_repo / FILE).write_text("new a\nnew b\n" + ORIGINAL)

        [annotation] = annotation_service.list_file_annotations(db, ws, project, repo="", file_path=FILE)

        assert (annotation["line_start"], annotation["line_end"], annotation["stale"]) == (5, 6, False)

    def test_list_file_annotations_should_use_ref_content_when_ref_given(self, db, ctx, annotated_repo):
        ws, project = ctx
        (annotated_repo / FILE).write_text("new a\nnew b\n" + ORIGINAL)
        _create(db, ctx, line_start=5, line_end=6)

        [at_head] = annotation_service.list_file_annotations(db, ws, project, repo="", file_path=FILE, ref="HEAD")

        assert (at_head["line_start"], at_head["line_end"], at_head["stale"]) == (3, 4, False)

    def test_list_file_annotations_should_mark_stale_when_anchor_lines_removed(self, db, ctx, annotated_repo):
        ws, project = ctx
        _create(db, ctx)
        (annotated_repo / FILE).write_text("only\n")

        [annotation] = annotation_service.list_file_annotations(db, ws, project, repo="", file_path=FILE)

        assert (annotation["line_start"], annotation["line_end"], annotation["stale"]) == (1, 1, True)

    def test_list_file_annotations_should_only_return_requested_file(self, db, ctx, annotated_repo):
        ws, project = ctx
        (annotated_repo / "other.py").write_text("x\n")
        _create(db, ctx)
        _create(db, ctx, file_path="other.py", line_start=1, line_end=1)

        result = annotation_service.list_file_annotations(db, ws, project, repo="", file_path=FILE)

        assert [a["file_path"] for a in result] == [FILE]

    def test_list_file_annotations_should_sort_by_resolved_line(self, db, ctx, annotated_repo):
        ws, project = ctx
        first = _create(db, ctx, line_start=2, line_end=2)
        second = _create(db, ctx, line_start=8, line_end=8)
        lines = ORIGINAL.splitlines()
        (annotated_repo / FILE).write_text("\n".join([lines[7]] + lines[:7] + lines[8:]) + "\n")

        result = annotation_service.list_file_annotations(db, ws, project, repo="", file_path=FILE)

        assert [a["id"] for a in result] == [second["id"], first["id"]]

    @pytest.mark.parametrize("ref,code", [("bad ref", "invalid_ref"), ("--help", "invalid_ref"),
                                          ("no-such-branch", "base_ref_not_found")])
    def test_list_file_annotations_should_reject_bad_ref(self, db, ctx, ref, code):
        ws, project = ctx

        with pytest.raises(AnnotationServiceError) as exc_info:
            annotation_service.list_file_annotations(db, ws, project, repo="", file_path=FILE, ref=ref)

        assert exc_info.value.code == code

    def test_list_file_annotations_should_report_file_not_found_when_absent_at_ref(
            self, db, ctx, annotated_repo):
        ws, project = ctx
        (annotated_repo / "uncommitted.py").write_text("x\n")

        with pytest.raises(AnnotationServiceError) as exc_info:
            annotation_service.list_file_annotations(db, ws, project, repo="", file_path="uncommitted.py", ref="HEAD")

        assert exc_info.value.code == "file_not_found"


class TestUpdateAnnotation:
    def test_update_annotation_should_change_text_only_when_only_text_given(self, db, ctx):
        ws, project = ctx
        created = _create(db, ctx)
        before = _stored_row(db, created["id"])

        updated = annotation_service.update_annotation(db, ws, project, created["id"], text="Revised")

        after = _stored_row(db, created["id"])
        assert (updated["text"], after["line_start"], after["line_end"], after["anchor_text"]) == (
            "Revised", before["line_start"], before["line_end"], before["anchor_text"])

    def test_update_annotation_should_recapture_anchor_when_range_changes(self, db, ctx):
        ws, project = ctx
        created = _create(db, ctx)

        annotation_service.update_annotation(db, ws, project, created["id"], line_start=6, line_end=8)

        row = _stored_row(db, created["id"])
        assert (row["line_start"], row["line_end"], row["anchor_text"]) == (6, 8, "line 6\nline 7\nline 8")

    def test_update_annotation_should_keep_stored_end_when_only_start_given(self, db, ctx):
        ws, project = ctx
        created = _create(db, ctx)

        annotation_service.update_annotation(db, ws, project, created["id"], line_start=2)

        assert _stored_row(db, created["id"])["anchor_text"] == "line 2\nline 3\nline 4"

    def test_update_annotation_should_recapture_from_working_tree_when_file_edited(
            self, db, ctx, annotated_repo):
        ws, project = ctx
        created = _create(db, ctx)
        (annotated_repo / FILE).write_text("edited\n" + ORIGINAL)

        annotation_service.update_annotation(db, ws, project, created["id"], line_start=1, line_end=1)

        assert _stored_row(db, created["id"])["anchor_text"] == "edited"

    def test_update_annotation_should_reject_empty_payload(self, db, ctx):
        ws, project = ctx
        created = _create(db, ctx)

        with pytest.raises(AnnotationServiceError) as exc_info:
            annotation_service.update_annotation(db, ws, project, created["id"])

        assert exc_info.value.code == "nothing_to_update"

    def test_update_annotation_should_reject_range_outside_file(self, db, ctx):
        ws, project = ctx
        created = _create(db, ctx)

        with pytest.raises(AnnotationServiceError) as exc_info:
            annotation_service.update_annotation(db, ws, project, created["id"], line_end=50)

        assert exc_info.value.code == "invalid_line_range"

    def test_update_annotation_should_raise_not_found_when_id_unknown(self, db, ctx):
        ws, project = ctx

        with pytest.raises(AnnotationServiceError) as exc_info:
            annotation_service.update_annotation(db, ws, project, 999999, text="x")

        assert exc_info.value.code == "not_found"


class TestDeleteAnnotation:
    def test_delete_annotation_should_remove_row(self, db, ctx, workspace):
        created = _create(db, ctx)

        annotation_service.delete_annotation(db, workspace["id"], created["id"])

        assert _stored_row(db, created["id"]) is None

    def test_delete_annotation_should_raise_not_found_when_id_unknown(self, db, ctx, workspace):
        with pytest.raises(AnnotationServiceError) as exc_info:
            annotation_service.delete_annotation(db, workspace["id"], 999999)

        assert exc_info.value.code == "not_found"

    def test_delete_annotation_should_not_touch_other_workspace_annotation(
            self, db, ctx, second_workspace):
        created = _create(db, ctx)

        with pytest.raises(AnnotationServiceError) as exc_info:
            annotation_service.delete_annotation(db, second_workspace["id"], created["id"])

        assert (exc_info.value.code, _stored_row(db, created["id"]) is not None) == ("not_found", True)


class TestCascade:
    def test_annotations_should_be_deleted_when_project_deleted(self, client, db, ctx, project):
        created = _create(db, ctx)
        db.commit()

        client.delete(f"/api/projects/{project['id']}")

        assert _stored_row(db, created["id"]) is None
