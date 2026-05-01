"""MCP tool for promoting proven research findings to memory_write proposals."""
from mcp.types import ToolAnnotations

from mcp_tools import TRANSIENT_DB_EXCEPTIONS, mcp, mcp_error, with_mcp_workspace
from services import memory_promotion_service
from services.memory_promotion_service import MemoryPromotionError


def _translate_memory_promotion_error(exc: MemoryPromotionError) -> dict:
    if exc.code == "not_found":
        return mcp_error("not_found", str(exc), retryable=False)
    if exc.code == "llm_unconfigured":
        return mcp_error(
            "business",
            str(exc),
            retryable=False,
            details={"hint": "Set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable LLM-gated promotion."},
        )
    if exc.code == "provider_unavailable":
        return mcp_error(
            "business",
            str(exc),
            retryable=False,
            details={"hint": "Enable the mempalace module to make the memory provider available."},
        )
    return mcp_error("transient", str(exc), retryable=True)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Promote research findings to memory proposals",
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def memory_promotion_run(ws, project, db, locale) -> dict:
    """Scan proven research entries and create memory_write proposals for project-level findings.

    Purpose
      Classifies each finding in proven research entries as project-level or
      ticket-specific. Project-level candidates are gated through an LLM
      applicability check and a semantic dedup step before a pending
      memory_write proposal is emitted. Proposals are not executed until
      approved by a human via the Proposals tab.

    Returns
      {workspace_id, candidates_examined, proposals_created, proposal_ids}

    Errors
      not_found   — workspace not detected for current directory.
      business    — LLM not configured, or memory provider unavailable; see hint in details.
      transient   — LLM call failed or DB error; caller may retry.
    """
    try:
        return memory_promotion_service.promote(db, ws["id"])
    except MemoryPromotionError as exc:
        return _translate_memory_promotion_error(exc)
    except TRANSIENT_DB_EXCEPTIONS as exc:
        return mcp_error("transient", str(exc), retryable=True)
