"""HTTP route tests for /api/ws/<project_id>/<branch>/annotations."""
from pathlib import Path

import pytest

from core.db import get_db
from testing_utils import _git

FILE = "src/app.py"
ORIGINAL = "".join(f"line {n}\n" for n in range(1, 11))
ANNOTATION_KEYS = {"id", "repo", "file_path", "line_start", "line_end", "text", "author",
                   "stale", "created_at", "updated_at"}


@pytest.fixture
def base_url(workspace, project, git_repo):
    repo = Path(git_repo)
    (repo / "src").mkdir()
    (repo / FILE).write_text(ORIGINAL)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Add app")
    return f"/api/ws/{project['id']}/{workspace['branch']}/annotations"


def _post(client, base_url, **overrides):
    body = {"file_path": FILE, "line_start": 3, "line_end": 4, "text": "Why"}
    body.update(overrides)
    return client.post(base_url, json=body)


def _create(client, base_url, **overrides):
    response = _post(client, base_url, **overrides)
    assert response.status_code == 201, response.json
    return response.json["annotation"]


def _annotation_count(workspace_id):
    db = get_db()
    try:
        return db.execute("SELECT COUNT(*) FROM annotations WHERE workspace_id = ?", (workspace_id,)).fetchone()[0]
    finally:
        db.close()


class TestCreateRoute:
    def test_post_should_return_201_with_annotation_contract(self, client, base_url):
        response = _post(client, base_url)

        assert (response.status_code, response.json["ok"], set(response.json["annotation"])) == (
            201, True, ANNOTATION_KEYS)

    def test_post_should_record_user_as_author(self, client, base_url):
        assert _create(client, base_url)["author"] == "user"

    def test_post_should_ignore_author_in_body(self, client, base_url):
        assert _create(client, base_url, author="mallory")["author"] == "user"

    @pytest.mark.parametrize("overrides,code", [
        ({"line_start": 5, "line_end": 4}, "invalid_line_range"),
        ({"line_end": 11}, "invalid_line_range"),
        ({"line_start": "3"}, "line_numbers_invalid"),
        ({"text": "  "}, "text_required"),
        ({"file_path": "../etc/passwd"}, "invalid_file_path"),
        ({"repo": "../elsewhere"}, "invalid_repo"),
    ])
    def test_post_should_return_400_with_code_when_invalid(self, client, base_url, overrides, code):
        response = _post(client, base_url, **overrides)

        assert (response.status_code, response.json["code"]) == (400, code)

    def test_post_should_include_human_message_in_error(self, client, base_url):
        response = _post(client, base_url, line_end=11)

        assert "3-11" in response.json["error"] and "10 lines" in response.json["error"]

    @pytest.mark.parametrize("overrides,code", [
        ({"file_path": "src/missing.py"}, "file_not_found"),
        ({"repo": "no-such-repo"}, "repo_not_found"),
    ])
    def test_post_should_return_404_with_code_when_target_missing(self, client, base_url, overrides, code):
        response = _post(client, base_url, **overrides)

        assert (response.status_code, response.json["code"]) == (404, code)

    def test_post_should_return_400_when_body_not_json(self, client, base_url):
        response = client.post(base_url, data="nope", content_type="text/plain")

        assert response.status_code == 400

    def test_post_should_return_404_when_workspace_unknown(self, client, base_url, project):
        response = _post(client, f"/api/ws/{project['id']}/no/such/branch/annotations")

        assert response.status_code == 404


class TestListRoute:
    def test_get_with_file_should_reanchor_against_uncommitted_working_tree(self, client, base_url, git_repo):
        _create(client, base_url)
        (Path(git_repo) / FILE).write_text("inserted\n" + ORIGINAL)

        [annotation] = client.get(base_url, query_string={"file": FILE}).json["annotations"]

        assert (annotation["line_start"], annotation["line_end"], annotation["stale"]) == (4, 5, False)

    def test_get_with_ref_head_should_differ_from_working_tree(self, client, base_url, git_repo):
        (Path(git_repo) / FILE).write_text("a\nb\nc\n" + ORIGINAL)
        _create(client, base_url, line_start=4, line_end=4)

        working = client.get(base_url, query_string={"file": FILE}).json["annotations"][0]
        at_head = client.get(base_url, query_string={"file": FILE, "ref": "HEAD"}).json["annotations"][0]

        assert (working["line_start"], at_head["line_start"]) == (4, 1)

    def test_get_with_empty_ref_should_use_working_tree(self, client, base_url, git_repo):
        (Path(git_repo) / FILE).write_text("a\n" + ORIGINAL)
        _create(client, base_url, line_start=2, line_end=2)

        [annotation] = client.get(base_url, query_string={"file": FILE, "ref": "  "}).json["annotations"]

        assert annotation["line_start"] == 2

    def test_get_with_file_should_report_stale_when_anchor_deleted(self, client, base_url, git_repo):
        _create(client, base_url)
        (Path(git_repo) / FILE).write_text("x\ny\n")

        [annotation] = client.get(base_url, query_string={"file": FILE}).json["annotations"]

        assert (annotation["line_start"], annotation["line_end"], annotation["stale"]) == (2, 2, True)

    def test_get_without_file_should_return_all_at_stored_lines(self, client, base_url, git_repo):
        (Path(git_repo) / "other.py").write_text("o\n")
        _create(client, base_url)
        _create(client, base_url, file_path="other.py", line_start=1, line_end=1)
        (Path(git_repo) / FILE).write_text("totally different\n")

        response = client.get(base_url)

        assert [(a["file_path"], a["line_start"], a["stale"]) for a in response.json["annotations"]] == [
            ("other.py", 1, False), (FILE, 3, False)]

    def test_get_should_return_empty_list_when_no_annotations(self, client, base_url):
        assert client.get(base_url).json == {"ok": True, "annotations": []}

    def test_get_with_file_should_return_404_when_file_missing(self, client, base_url):
        response = client.get(base_url, query_string={"file": "nope.py"})

        assert (response.status_code, response.json["code"]) == (404, "file_not_found")

    @pytest.mark.parametrize("ref,code", [("a:b", "invalid_ref"), ("missing-branch", "base_ref_not_found")])
    def test_get_with_bad_ref_should_return_400(self, client, base_url, ref, code):
        response = client.get(base_url, query_string={"file": FILE, "ref": ref})

        assert (response.status_code, response.json["code"]) == (400, code)

    def test_get_should_not_leak_other_workspace_annotations(self, client, base_url, project, second_workspace):
        _create(client, base_url)

        response = client.get(f"/api/ws/{project['id']}/{second_workspace['branch']}/annotations")

        assert response.json["annotations"] == []


class TestUpdateRoute:
    def test_patch_text_only_should_keep_range(self, client, base_url):
        created = _create(client, base_url)

        response = client.patch(f"{base_url}/{created['id']}", json={"text": "New"})

        updated = response.json["annotation"]
        assert (response.status_code, updated["text"], updated["line_start"], updated["line_end"]) == (
            200, "New", 3, 4)

    def test_patch_range_only_should_recapture_anchor(self, client, base_url, git_repo):
        created = _create(client, base_url)
        client.patch(f"{base_url}/{created['id']}", json={"line_start": 7, "line_end": 7})
        (Path(git_repo) / FILE).write_text("top\n" + ORIGINAL)

        [annotation] = client.get(base_url, query_string={"file": FILE}).json["annotations"]

        assert (annotation["line_start"], annotation["text"], annotation["stale"]) == (8, "Why", False)

    @pytest.mark.parametrize("body,code", [
        ({}, "nothing_to_update"),
        ({"text": ""}, "text_required"),
        ({"line_end": 99}, "invalid_line_range"),
        ({"line_start": "x"}, "line_numbers_invalid"),
    ])
    def test_patch_should_return_400_with_code_when_invalid(self, client, base_url, body, code):
        created = _create(client, base_url)

        response = client.patch(f"{base_url}/{created['id']}", json=body)

        assert (response.status_code, response.json["code"]) == (400, code)

    def test_patch_should_return_404_when_id_unknown(self, client, base_url):
        response = client.patch(f"{base_url}/999999", json={"text": "x"})

        assert (response.status_code, response.json["code"]) == (404, "not_found")

    def test_patch_range_should_return_404_when_file_deleted(self, client, base_url, git_repo):
        created = _create(client, base_url)
        (Path(git_repo) / FILE).unlink()

        response = client.patch(f"{base_url}/{created['id']}", json={"line_start": 1})

        assert (response.status_code, response.json["code"]) == (404, "file_not_found")


class TestDeleteRoute:
    def test_delete_should_remove_annotation(self, client, base_url, workspace):
        created = _create(client, base_url)

        response = client.delete(f"{base_url}/{created['id']}")

        assert (response.status_code, response.json, _annotation_count(workspace["id"])) == (200, {"ok": True}, 0)

    def test_delete_should_return_404_when_id_unknown(self, client, base_url):
        response = client.delete(f"{base_url}/999999")

        assert (response.status_code, response.json["code"]) == (404, "not_found")

    def test_delete_should_return_404_when_annotation_in_other_workspace(
            self, client, base_url, project, second_workspace):
        created = _create(client, base_url)

        response = client.delete(f"/api/ws/{project['id']}/{second_workspace['branch']}/annotations/{created['id']}")

        assert response.status_code == 404


class TestArchive:
    def test_archive_should_delete_workspace_annotations(self, client, base_url, project, workspace):
        _create(client, base_url)

        client.put(f"/api/ws/{project['id']}/{workspace['branch']}/archive")

        assert _annotation_count(workspace["id"]) == 0


class TestAuth:
    @pytest.mark.parametrize("method,suffix", [("get", ""), ("post", ""), ("patch", "/1"), ("delete", "/1")])
    def test_routes_should_return_401_without_token(self, raw_client, base_url, method, suffix):
        response = getattr(raw_client, method)(f"{base_url}{suffix}", json={})

        assert response.status_code == 401


def _create_multi_workspace_with_repo(client, multi_project, branch):
    response = client.post(f"/api/projects/{multi_project['id']}/workspaces",
                           json={"branch": branch, "worktree": True})
    assert response.status_code == 201, response.json
    attach = client.post(f"/api/ws/{multi_project['id']}/{branch}/repos/attach",
                         json={"repo_id": multi_project["repos"]["service-a"]["id"]})
    assert attach.status_code == 200, attach.json
    worktree = Path(attach.json["attached"]["worktree_path"])
    (worktree / "svc.py").write_text("a\nb\nc\n")
    return f"/api/ws/{multi_project['id']}/{branch}/annotations"


class TestMultiRepo:
    def test_post_should_store_repo_when_attached_repo_given(self, client, multi_project):
        url = _create_multi_workspace_with_repo(client, multi_project, "feature/annot-multi")

        created = _create(client, url, repo="service-a", file_path="svc.py", line_start=2, line_end=2)

        assert created["repo"] == "service-a"

    def test_get_should_resolve_file_in_attached_repo(self, client, multi_project):
        url = _create_multi_workspace_with_repo(client, multi_project, "feature/annot-multi-get")
        _create(client, url, repo="service-a", file_path="svc.py", line_start=2, line_end=2)

        response = client.get(url, query_string={"file": "svc.py", "repo": "service-a"})

        assert [a["line_start"] for a in response.json["annotations"]] == [2]

    def test_post_should_return_400_repo_required_when_repo_omitted(self, client, multi_project):
        url = _create_multi_workspace_with_repo(client, multi_project, "feature/annot-multi-req")

        response = _post(client, url, file_path="svc.py", line_start=1, line_end=1)

        assert (response.status_code, response.json["code"]) == (400, "repo_required")

    def test_post_should_return_404_when_repo_not_attached(self, client, multi_project):
        url = _create_multi_workspace_with_repo(client, multi_project, "feature/annot-multi-404")

        response = _post(client, url, repo="service-b", file_path="svc.py", line_start=1, line_end=1)

        assert (response.status_code, response.json["code"]) == (404, "repo_not_found")

    def test_get_should_scope_annotations_by_repo(self, client, multi_project):
        url = _create_multi_workspace_with_repo(client, multi_project, "feature/annot-multi-scope")
        _create(client, url, repo="service-a", file_path="svc.py", line_start=1, line_end=1)
        client.post(f"{url.rsplit('/annotations', 1)[0]}/repos/attach",
                    json={"repo_id": multi_project["repos"]["service-b"]["id"]})
        worktree_b = Path(multi_project["path"]) / ".claude" / "worktrees" / "feature-annot-multi-scope" / "service-b"
        (worktree_b / "svc.py").write_text("a\n")

        response = client.get(url, query_string={"file": "svc.py", "repo": "service-b"})

        assert response.json["annotations"] == []
