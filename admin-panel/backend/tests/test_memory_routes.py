"""Tests for memory REST endpoints under /api/ws/<project_id>/<branch>/memory."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.memory_provider import MemoryProviderError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MEMORY_DICT = {
    "memory_id": "mem-1",
    "content": "test memory content",
    "scope": {"kind": "project", "project_id": "test-project"},
    "metadata": {},
    "created_at": "2024-01-01T00:00:00",
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


# ---------------------------------------------------------------------------
# POST /api/ws/<project_id>/<branch>/memory
# ---------------------------------------------------------------------------

class TestSaveMemoryRoute:
    def test_post_memory_returns_201_on_save(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch("routes.memory.memory_service.save", return_value=_MEMORY_DICT):
            response = client.post(
                f"/api/ws/{project_id}/{branch}/memory",
                json={"content": "test memory content", "scope": {"kind": "project"}},
            )

        assert response.status_code == 201
        data = response.get_json()
        assert data["memory_id"] == "mem-1"
        assert data["content"] == "test memory content"

    def test_post_memory_returns_503_when_provider_unavailable_with_hint(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.memory.memory_service.save",
            side_effect=MemoryProviderError(
                code="provider_unavailable",
                message="mempalace not installed",
            ),
        ):
            response = client.post(
                f"/api/ws/{project_id}/{branch}/memory",
                json={"content": "note", "scope": {"kind": "project"}},
            )

        assert response.status_code == 503
        data = response.get_json()
        assert "error" in data
        assert "hint" in data

    def test_post_memory_returns_400_on_invalid_scope(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.memory.memory_service.save",
            side_effect=MemoryProviderError(code="invalid_scope", message="scope malformed"),
        ):
            response = client.post(
                f"/api/ws/{project_id}/{branch}/memory",
                json={"content": "note", "scope": "bad"},
            )

        assert response.status_code == 400
        assert "error" in response.get_json()


# ---------------------------------------------------------------------------
# GET /api/ws/<project_id>/<branch>/memory
# ---------------------------------------------------------------------------

class TestListMemoriesRoute:
    def test_get_memory_list_returns_200(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.memory.memory_service.list_memories",
            return_value=[_MEMORY_DICT],
        ):
            response = client.get(f"/api/ws/{project_id}/{branch}/memory")

        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["memory_id"] == "mem-1"

    def test_get_memory_list_with_scope_filter_query_param(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        scope_filter_encoded = json.dumps({"kind": "project", "project_id": "test-project"})
        captured = {}

        def _capture_list(db, scope_filter=None):
            captured["scope_filter"] = scope_filter
            return [_MEMORY_DICT]

        with patch("routes.memory.memory_service.list_memories", side_effect=_capture_list):
            response = client.get(
                f"/api/ws/{project_id}/{branch}/memory",
                query_string={"scope_filter": scope_filter_encoded},
            )

        assert response.status_code == 200
        assert captured["scope_filter"] == [{"kind": "project", "project_id": "test-project"}]

    def test_get_memory_list_returns_404_for_missing_workspace(self, client, clean_db):
        response = client.get("/api/ws/nonexistent/nonexistent-branch/memory")

        assert response.status_code == 404

    def test_get_memory_list_returns_503_when_provider_unavailable(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.memory.memory_service.list_memories",
            side_effect=MemoryProviderError(code="provider_unavailable", message="not installed"),
        ):
            response = client.get(f"/api/ws/{project_id}/{branch}/memory")

        assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/ws/<project_id>/<branch>/memory/<memory_id>
# ---------------------------------------------------------------------------

class TestGetMemoryByIdRoute:
    def test_get_memory_by_id_returns_200(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch("routes.memory.memory_service.get", return_value=_MEMORY_DICT):
            response = client.get(f"/api/ws/{project_id}/{branch}/memory/mem-1")

        assert response.status_code == 200
        data = response.get_json()
        assert data["memory_id"] == "mem-1"
        assert data["content"] == "test memory content"

    def test_get_memory_by_unknown_id_returns_404(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.memory.memory_service.get",
            side_effect=MemoryProviderError(code="memory_not_found", message="not found"),
        ):
            response = client.get(f"/api/ws/{project_id}/{branch}/memory/nonexistent")

        assert response.status_code == 404
        assert "error" in response.get_json()


# ---------------------------------------------------------------------------
# DELETE /api/ws/<project_id>/<branch>/memory/<memory_id>
# ---------------------------------------------------------------------------

class TestDeleteMemoryRoute:
    def test_delete_memory_returns_200_with_ok(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch("routes.memory.memory_service.delete", return_value=True):
            response = client.delete(f"/api/ws/{project_id}/{branch}/memory/mem-1")

        assert response.status_code in (200, 204)
        if response.status_code == 200:
            data = response.get_json()
            assert data["ok"] is True
            assert data["deleted_id"] == "mem-1"

    def test_delete_memory_returns_404_when_not_found(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.memory.memory_service.delete",
            side_effect=MemoryProviderError(code="memory_not_found", message="not found"),
        ):
            response = client.delete(f"/api/ws/{project_id}/{branch}/memory/nonexistent")

        assert response.status_code == 404
        assert "error" in response.get_json()


# ---------------------------------------------------------------------------
# POST /api/ws/<project_id>/<branch>/memory/search
# ---------------------------------------------------------------------------

class TestSearchMemoriesRoute:
    def test_post_search_returns_200_with_results(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        retrieved = {**_MEMORY_DICT, "score": 0.95}
        with patch("routes.memory.memory_service.retrieve", return_value=[retrieved]):
            response = client.post(
                f"/api/ws/{project_id}/{branch}/memory/search",
                json={"query": "find notes", "limit": 5},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        assert data[0]["score"] == 0.95

    def test_post_search_returns_400_on_invalid_scope(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.memory.memory_service.retrieve",
            side_effect=MemoryProviderError(code="invalid_scope", message="query empty"),
        ):
            response = client.post(
                f"/api/ws/{project_id}/{branch}/memory/search",
                json={"query": ""},
            )

        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_post_search_returns_503_when_provider_unavailable(self, client, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            project_id, branch, _ = _make_workspace(db)
        finally:
            db.close()

        with patch(
            "routes.memory.memory_service.retrieve",
            side_effect=MemoryProviderError(code="provider_unavailable", message="not installed"),
        ):
            response = client.post(
                f"/api/ws/{project_id}/{branch}/memory/search",
                json={"query": "find notes"},
            )

        assert response.status_code == 503
