"""Single source of truth for the proposal type taxonomy.

Used by the service-layer validator, the MCP tool type hint, the reflection
prompt, the REST endpoint ``GET /api/proposals/types``, and the frontend
filter. Adding a new type requires editing ONE value here; everything else
derives from it.

The SQL CHECK constraint that previously enumerated these values inline was
removed via migration 0032_drop_proposals_type_check (Option A). Python-layer
validation in ``proposal_service._validate_type`` is now the authoritative
gate; the database no longer enforces an enum constraint on the type column.
"""
from enum import Enum


class ProposalType(str, Enum):
    MEMORY_WRITE = "memory_write"
    MEMORY_DELETE = "memory_delete"
    RULE_NEW = "rule_new"
    RULE_UPDATE = "rule_update"
    AGENT_NEW = "agent_new"
    AGENT_UPDATE = "agent_update"
    SKILL_NEW = "skill_new"
    SKILL_UPDATE = "skill_update"
    WORKFLOW_IMPROVEMENT = "workflow_improvement"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(t.value for t in cls)
