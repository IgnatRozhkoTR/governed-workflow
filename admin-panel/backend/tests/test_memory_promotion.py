"""Tests for memory_promotion_service.promote()."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from core.llm_client import LLMClientError
from services.memory_promotion_service import MemoryPromotionError
from services.memory_provider import MemoryProviderError
from services import memory_promotion_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace(db, project_id: str = "test-project") -> int:
    db.execute(
        "INSERT OR IGNORE INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", "/tmp/test", "2024-01-01"),
    )
    cursor = db.execute(
        "INSERT INTO workspaces "
        "(project_id, branch, sanitized_branch, working_dir, created, status, phase, scope_json, plan_json, source_branch) "
        "VALUES (?, 'feature/x', 'feature-x', '/tmp/test', '2024-01-01', 'active', '0', '{}', '{}', 'main')",
        (project_id,),
    )
    ws_id = cursor.lastrowid
    db.commit()
    return ws_id


def _insert_proven_entry(db, workspace_id: int, findings: list, topic: str = "test-topic") -> int:
    cursor = db.execute(
        "INSERT INTO research_entries (workspace_id, topic, findings_json, proven, created_at) "
        "VALUES (?, ?, ?, 1, '2024-01-01T00:00:00')",
        (workspace_id, topic, json.dumps(findings)),
    )
    db.commit()
    return cursor.lastrowid


def _noop_retrieve(*args, **kwargs):
    return []


def _noop_llm_yes(*args, **kwargs):
    return "YES it is broadly applicable."


# ---------------------------------------------------------------------------
# Heuristic split
# ---------------------------------------------------------------------------

class TestHeuristicSplit:
    def test_promote_classifies_finding_with_architecture_term_as_project_level(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {"summary": "Use architecture layering", "details": "Keep layers separate.", "proof": {"files": []}}
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES applicable."),
                patch("services.memory_promotion_service.memory_service.retrieve", return_value=[]),
            ):
                result = memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        assert result["candidates_examined"] == 1
        assert result["proposals_created"] == 1

    def test_promote_classifies_finding_with_no_arch_terms_as_ticket_specific(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {"summary": "Fix null check in login", "details": "Added guard clause.", "proof": {"files": ["a.py"]}}
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES applicable."),
                patch("services.memory_promotion_service.memory_service.retrieve", return_value=[]),
            ):
                result = memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        assert result["candidates_examined"] == 0
        assert result["proposals_created"] == 0

    def test_promote_classifies_recurring_title_as_project_level(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            # Same normalized title in two different entries
            _insert_proven_entry(db, ws_id, [
                {"summary": "Always validate inputs", "details": "Validate at boundaries.", "proof": {"files": []}}
            ])
            _insert_proven_entry(db, ws_id, [
                {"summary": "Always validate inputs", "details": "Repeat reminder.", "proof": {"files": []}}
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES applicable."),
                patch("services.memory_promotion_service.memory_service.retrieve", return_value=[]),
            ):
                result = memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        # Both findings are project-level due to recurrence
        assert result["candidates_examined"] == 2
        assert result["proposals_created"] == 2


# ---------------------------------------------------------------------------
# LLM gate
# ---------------------------------------------------------------------------

class TestLLMGate:
    def test_promote_skips_finding_when_llm_returns_NO(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {"summary": "architectural pattern observed", "details": "Worth noting.", "proof": {"files": []}}
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="NO this is too specific."),
                patch("services.memory_promotion_service.memory_service.retrieve", return_value=[]),
            ):
                result = memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        assert result["candidates_examined"] == 1
        assert result["proposals_created"] == 0

    def test_promote_keeps_finding_when_llm_returns_YES(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {"summary": "architectural pattern observed", "details": "Worth noting.", "proof": {"files": []}}
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES broadly applicable."),
                patch("services.memory_promotion_service.memory_service.retrieve", return_value=[]),
            ):
                result = memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        assert result["candidates_examined"] == 1
        assert result["proposals_created"] == 1


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

class TestDedup:
    def test_promote_skips_when_provider_retrieve_returns_high_relevance(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {"summary": "architectural convention", "details": "Already known.", "proof": {"files": []}}
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES applicable."),
                patch(
                    "services.memory_promotion_service.memory_service.retrieve",
                    return_value=[{"score": 0.9, "content": "existing memory"}],
                ),
            ):
                result = memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        assert result["candidates_examined"] == 1
        assert result["proposals_created"] == 0

    def test_promote_keeps_when_provider_retrieve_returns_low_relevance(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {"summary": "architectural convention", "details": "Novel finding.", "proof": {"files": []}}
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES applicable."),
                patch(
                    "services.memory_promotion_service.memory_service.retrieve",
                    return_value=[{"score": 0.5, "content": "distant memory"}],
                ),
            ):
                result = memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        assert result["candidates_examined"] == 1
        assert result["proposals_created"] == 1

    def test_promote_keeps_when_provider_retrieve_returns_empty(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {"summary": "architectural convention", "details": "No prior memory.", "proof": {"files": []}}
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES applicable."),
                patch("services.memory_promotion_service.memory_service.retrieve", return_value=[]),
            ):
                result = memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        assert result["candidates_examined"] == 1
        assert result["proposals_created"] == 1


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_promote_creates_proposals_with_correct_payload(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {
                    "id": "finding-42",
                    "summary": "architectural convention for service layer",
                    "details": "Services must not call routes.",
                    "proof": {"files": []},
                }
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES applicable."),
                patch("services.memory_promotion_service.memory_service.retrieve", return_value=[]),
            ):
                result = memory_promotion_service.promote(db, ws_id)

            assert result["proposals_created"] == 1
            proposal_id = result["proposal_ids"][0]
            row = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        finally:
            db.close()

        assert row is not None
        assert row["origin"] == "memory_promotion"
        assert row["type"] == "memory_write"
        payload = json.loads(row["payload_json"])
        assert "content" in payload
        assert payload["scope"]["kind"] == "project"
        assert "tags" in payload["metadata"]
        assert "source_research_id" in payload["metadata"]

    def test_promote_returns_correct_counts(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {"summary": "architectural pattern alpha", "details": "Detail alpha.", "proof": {"files": []}},
                {"summary": "architectural pattern beta", "details": "Detail beta.", "proof": {"files": []}},
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES applicable."),
                patch("services.memory_promotion_service.memory_service.retrieve", return_value=[]),
            ):
                result = memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        assert result["workspace_id"] == ws_id
        assert result["candidates_examined"] == 2
        assert result["proposals_created"] == 2
        assert len(result["proposal_ids"]) == 2

    def test_promote_no_back_reference_to_research_in_proposal_body(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {
                    "summary": "architectural convention",
                    "details": "Keep domain logic in services.",
                    "proof": {"files": []},
                }
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES applicable."),
                patch("services.memory_promotion_service.memory_service.retrieve", return_value=[]),
            ):
                result = memory_promotion_service.promote(db, ws_id)

            proposal_id = result["proposal_ids"][0]
            row = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        finally:
            db.close()

        assert row["body"] == "Keep domain logic in services."
        # research_entry_id must not be a direct column on the proposal row
        assert "research_entry_id" not in row.keys()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class TestErrors:
    def test_promote_raises_not_found_for_unknown_workspace(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            with pytest.raises(MemoryPromotionError) as exc_info:
                memory_promotion_service.promote(db, 99999)
        finally:
            db.close()

        assert exc_info.value.code == "not_found"

    def test_promote_raises_llm_unconfigured_when_env_missing(self, clean_db, monkeypatch):
        from core.db import get_db

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {"summary": "architectural convention", "details": "Detail.", "proof": {"files": []}}
            ])
            with pytest.raises(MemoryPromotionError) as exc_info:
                memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        assert exc_info.value.code == "llm_unconfigured"

    def test_promote_raises_provider_unavailable_when_mempalace_missing(self, clean_db):
        from core.db import get_db

        db = get_db()
        try:
            ws_id = _make_workspace(db)
            _insert_proven_entry(db, ws_id, [
                {"summary": "architectural convention", "details": "Detail.", "proof": {"files": []}}
            ])
            with (
                patch("services.memory_promotion_service.llm_client.complete", return_value="YES applicable."),
                patch(
                    "services.memory_promotion_service.memory_service.retrieve",
                    side_effect=MemoryProviderError(code="provider_unavailable", message="mempalace not installed"),
                ),
                pytest.raises(MemoryPromotionError) as exc_info,
            ):
                memory_promotion_service.promote(db, ws_id)
        finally:
            db.close()

        assert exc_info.value.code == "provider_unavailable"
