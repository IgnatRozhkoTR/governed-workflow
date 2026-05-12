"""Tests for reflection REST endpoints under /api/ws/<project_id>/<branch>/reflections."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.reflection_service import ReflectionServiceError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REFLECTION_DICT = {
    "id": 1,
    "workspace_id": 10,
    "content_md": "## What was done\nStuff.",
    "summary": "Stuff done.",
    "session_id": "sess-abc",
    "created_at": "2024-01-01T10:00:00",
}


def _make_workspace(db) -> tuple[str, str, int]:
    db.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        ("test-project", "Test Project", "/tmp/test", "2024-01-01"),
    )
    cursor = db.execute(
        "INSERT INTO workspaces "
        "(project_id, branch, sanitized_branch, working_dir, created, status, phase, scope_json, plan_json, source_branch) "
        "VALUES ('test-project', 'feature/x', 'feature-x', '/tmp/test', '2024-01-01', 'active', '0', '{}', '{}', 'main')"
    )
    ws_id = cursor.lastrowid
    db.commit()
    return ("test-project", "feature/x", ws_id)


def _insert_reflection(db, ws_id: int, created_at: str = "2024-01-01T10:00:00") -> int:
    cursor = db.execute(
        "INSERT INTO reflections (workspace_id, content_md, summary, session_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ws_id, "## Report\nContent.", "Short summary.", "sess-xyz", created_at),
    )
    db.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# POST /api/ws/<project_id>/<branch>/reflections
# ---------------------------------------------------------------------------

class TestRunReflectionRoute:
    def test_post_reflection_returns_201_on_success(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, ws_id = _make_workspace(db)
        finally:
            db.close()

        with patch("routes.reflections.reflection_service.run", return_value={**_REFLECTION_DICT, "workspace_id": ws_id}):
            response = client.post(f"/api/ws/{project_id}/{branch}/reflections")

        assert response.status_code == 201
        data = response.get_json()
        assert "id" in data
        assert "content_md" in data
        assert "summary" in data

    def test_post_reflection_returns_503_when_llm_unconfigured(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, ws_id = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.reflections.reflection_service.run",
            side_effect=ReflectionServiceError("no key", code="llm_unconfigured"),
        ):
            response = client.post(f"/api/ws/{project_id}/{branch}/reflections")

        assert response.status_code == 503
        assert "error" in response.get_json()

    def test_post_reflection_returns_502_on_llm_failure(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, ws_id = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.reflections.reflection_service.run",
            side_effect=ReflectionServiceError("api timed out", code="llm_failure"),
        ):
            response = client.post(f"/api/ws/{project_id}/{branch}/reflections")

        assert response.status_code == 502
        assert "error" in response.get_json()

    def test_post_reflection_returns_409_when_no_session_found(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, ws_id = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.reflections.reflection_service.run",
            side_effect=ReflectionServiceError("no JSONL", code="no_session_found"),
        ):
            response = client.post(f"/api/ws/{project_id}/{branch}/reflections")

        assert response.status_code == 409
        assert "error" in response.get_json()

    def test_post_reflection_returns_502_on_llm_invalid_json(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, ws_id = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.reflections.reflection_service.run",
            side_effect=ReflectionServiceError("LLM returned malformed JSON", code="llm_invalid_json"),
        ):
            response = client.post(f"/api/ws/{project_id}/{branch}/reflections")

        assert response.status_code == 502
        assert "error" in response.get_json()

    def test_post_reflection_returns_proposal_ids_in_body(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, ws_id = _make_workspace(db)
        finally:
            db.close()

        service_result = {**_REFLECTION_DICT, "workspace_id": ws_id, "proposal_ids": [42, 43]}
        with patch("routes.reflections.reflection_service.run", return_value=service_result):
            response = client.post(f"/api/ws/{project_id}/{branch}/reflections")

        assert response.status_code == 201
        data = response.get_json()
        assert data["proposal_ids"] == [42, 43]


# ---------------------------------------------------------------------------
# GET /api/ws/<project_id>/<branch>/reflections
# ---------------------------------------------------------------------------

class TestListReflectionsRoute:
    def test_get_reflection_list_returns_200_with_rows(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, ws_id = _make_workspace(db)
            _insert_reflection(db, ws_id, "2024-01-02T09:00:00")
            _insert_reflection(db, ws_id, "2024-01-01T09:00:00")
        finally:
            db.close()

        response = client.get(f"/api/ws/{project_id}/{branch}/reflections")

        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert all("id" in item for item in data)

    def test_get_reflection_list_returns_404_for_missing_workspace(self, client, clean_db):
        response = client.get("/api/ws/nonexistent-project/nonexistent-branch/reflections")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/ws/<project_id>/<branch>/reflections/<rid>
# ---------------------------------------------------------------------------

class TestGetReflectionByIdRoute:
    def test_get_reflection_by_id_returns_200(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, ws_id = _make_workspace(db)
            rid = _insert_reflection(db, ws_id)
        finally:
            db.close()

        response = client.get(f"/api/ws/{project_id}/{branch}/reflections/{rid}")

        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == rid
        assert data["workspace_id"] == ws_id

    def test_get_reflection_by_unknown_id_returns_404(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, ws_id = _make_workspace(db)
        finally:
            db.close()

        response = client.get(f"/api/ws/{project_id}/{branch}/reflections/99999")

        assert response.status_code == 404
        assert "error" in response.get_json()


# ---------------------------------------------------------------------------
# Locale-switching tests (i18n contract)
# ---------------------------------------------------------------------------

class TestReflectionRoutesLocale:
    def _make_workspace_with_locale(self, db, locale: str) -> tuple[str, str, int]:
        db.execute(
            "INSERT OR IGNORE INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
            ("test-project", "Test Project", "/tmp/test", "2024-01-01"),
        )
        cursor = db.execute(
            "INSERT INTO workspaces "
            "(project_id, branch, sanitized_branch, working_dir, created, status, phase, scope_json, plan_json, source_branch, locale) "
            "VALUES ('test-project', 'feature/x', 'feature-x', '/tmp/test', '2024-01-01', 'active', '0', '{}', '{}', 'main', ?)",
            (locale,),
        )
        ws_id = cursor.lastrowid
        db.commit()
        return ("test-project", "feature/x", ws_id)

    def test_llm_unconfigured_error_is_russian_when_locale_ru(self, client, clean_db):
        from core.db import get_db
        from core.i18n import t, reload

        reload()
        db = get_db()
        try:
            project_id, branch, ws_id = self._make_workspace_with_locale(db, "ru")
        finally:
            db.close()

        with patch(
            "routes.reflections.reflection_service.run",
            side_effect=ReflectionServiceError("no key", code="llm_unconfigured"),
        ):
            response = client.post(f"/api/ws/{project_id}/{branch}/reflections")

        assert response.status_code == 503
        data = response.get_json()
        assert data["error"] == t("api.error.reflection.llmUnconfigured", "ru")
