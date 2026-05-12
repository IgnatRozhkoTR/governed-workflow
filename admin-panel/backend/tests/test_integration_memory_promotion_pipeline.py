"""End-to-end pipeline: memory_promotion.promote → proposals (origin='memory_promotion').

Mocks the LLM gate and dedup retrieve calls (neither is available in tests). The
proposal storage uses the real service. Approval is a pure status flip — no
downstream side-effects to assert beyond the project-level filter behavior.
"""
import json
from unittest.mock import patch

from core.db import get_db
from services import memory_promotion_service


_PROJECT_LEVEL_FINDING = {
    "id": "finding-1",
    "summary": "architectural convention for service layer",
    "details": "Services must not call routes directly.",
    "proof": {"files": []},
}

_TICKET_SPECIFIC_FINDING = {
    "id": "finding-2",
    "summary": "Fix null check in login form",
    "details": "Added guard clause for missing email field.",
    "proof": {"files": ["src/login.py"]},
}


def _insert_proven_entry(db, workspace_id: int, findings: list[dict]) -> int:
    cursor = db.execute(
        "INSERT INTO research_entries (workspace_id, topic, findings_json, proven, created_at) "
        "VALUES (?, ?, ?, 1, '2024-01-01T00:00:00')",
        (workspace_id, "test-topic", json.dumps(findings)),
    )
    db.commit()
    return cursor.lastrowid


def test_promote_emits_only_project_level_proposals(clean_db, project, workspace):
    """A research entry with one project-level finding and one ticket-specific
    finding produces exactly one memory_write proposal (origin='memory_promotion')."""
    db = get_db()
    try:
        _insert_proven_entry(
            db,
            workspace["id"],
            [_PROJECT_LEVEL_FINDING, _TICKET_SPECIFIC_FINDING],
        )

        with (
            patch(
                "services.memory_promotion_service.llm_client.complete",
                return_value="YES broadly applicable.",
            ),
            patch(
                "services.memory_promotion_service.memory_service.retrieve",
                return_value=[],
            ),
        ):
            result = memory_promotion_service.promote(db, workspace["id"])

        proposals = db.execute(
            "SELECT * FROM proposals WHERE origin = 'memory_promotion' ORDER BY id"
        ).fetchall()
    finally:
        db.close()

    assert result["candidates_examined"] == 1
    assert result["proposals_created"] == 1
    assert len(proposals) == 1

    assert proposals[0]["type"] == "memory_write"
    assert proposals[0]["origin"] == "memory_promotion"
    assert proposals[0]["title"] == _PROJECT_LEVEL_FINDING["summary"]
    assert proposals[0]["body"] == _PROJECT_LEVEL_FINDING["details"]
