"""End-to-end pipeline: memory_promotion.promote → proposals (origin='memory_promotion') → admin approval.

Mocks the LLM gate and dedup retrieve calls (neither is available in tests). The
proposal storage and executor side-effects use the real services. The mock for
`memory_service.save` lets us assert call arguments downstream.
"""
import json
from unittest.mock import patch

from core.db import get_db
from services import memory_promotion_service, proposal_service


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

    payload = json.loads(proposals[0]["payload_json"])
    assert proposals[0]["type"] == "memory_write"
    assert proposals[0]["origin"] == "memory_promotion"
    assert proposals[0]["title"] == _PROJECT_LEVEL_FINDING["summary"]
    assert payload["scope"]["kind"] == "project"
    assert payload["metadata"]["source_research_id"] == _PROJECT_LEVEL_FINDING["id"]


def test_promotion_proposals_can_be_approved_and_executed(
    clean_db, project, workspace
):
    """Approving a memory_promotion proposal calls memory_service.save with the
    correct payload and lands the proposal in 'executed'."""
    db = get_db()
    try:
        _insert_proven_entry(db, workspace["id"], [_PROJECT_LEVEL_FINDING])

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
            promote_result = memory_promotion_service.promote(db, workspace["id"])

        assert len(promote_result["proposal_ids"]) == 1
        proposal_id = promote_result["proposal_ids"][0]

        save_return = {
            "memory_id": "mem-promoted-1",
            "content": _PROJECT_LEVEL_FINDING["details"],
        }
        with patch(
            "services.proposal_executor.memory_service.save",
            return_value=save_return,
        ) as mock_save:
            approved = proposal_service.approve(db, proposal_id)
    finally:
        db.close()

    assert approved["status"] == "executed"
    assert approved["result"]["memory_id"] == "mem-promoted-1"

    mock_save.assert_called_once()
    call_args = mock_save.call_args
    assert call_args.args[0] == _PROJECT_LEVEL_FINDING["details"]
    assert call_args.args[1]["kind"] == "project"
    metadata = call_args.args[2]
    assert "research-promoted" in metadata["tags"]
    assert metadata["source_research_id"] == _PROJECT_LEVEL_FINDING["id"]
