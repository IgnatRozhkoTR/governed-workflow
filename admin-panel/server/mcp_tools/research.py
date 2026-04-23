from typing import Annotated, Literal

from pydantic import Field
from mcp.types import ToolAnnotations

from mcp_tools import mcp, with_mcp_workspace, mcp_error
from core.i18n import t
from services import discussion_service
from services import research_service


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False))
@with_mcp_workspace
def workspace_post_discussion(
    ws, project, db, locale,
    topic: Annotated[str, Field(description="Short title or question for the discussion (e.g. 'Should we use event-driven logging?').")],
    parent_id: Annotated[int, Field(description="ID of the parent discussion to reply to. Use 0 to open a new root discussion.")] = 0,
    type: Annotated[Literal["general", "research"], Field(description="'research' discussions must have linked research entries before advancing past the research phase. Use 'general' for architectural decisions and open questions.")] = "general",
) -> dict:
    """Raise an open discussion point — architectural decisions, research questions, TBDs.

    These are NOT chat messages. They are important topics that need research, discussion,
    or decision from either the agent or the human. Examples:
    - 'Should we use event-driven logging or centralized logger?'
    - 'Hibernate Envers vs custom audit implementation'
    - 'Async vs sync approach for trade operation logging'

    Discussions are visible in the admin panel where either side can add context and resolve them.
    Use parent_id to reply to an existing discussion (0 = new root discussion).

    Returns
      {ok: True, discussion_id: int}

    Errors
      - not_found: parent_id does not exist.
    """
    result = discussion_service.post_discussion(
        db, ws["id"], topic, author="agent",
        disc_type=type, parent_id=parent_id if parent_id else None,
    )
    if "error" in result:
        return mcp_error(
            "not_found",
            t("mcp.error.parentDiscussionNotFound", locale, id=result.get("parent_id", "")),
            retryable=False,
        )
    db.commit()
    return {"ok": True, "discussion_id": result["id"]}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False))
@with_mcp_workspace
def workspace_save_research(
    ws, project, db, locale,
    topic: Annotated[str, Field(description="Short title of what was investigated.")],
    findings: Annotated[list, Field(description=(
        "List of {summary, details, proof} dicts. Each finding must include a typed proof: "
        "'code' shape: {type, file, line_start, line_end, snippet_start, snippet_end}; "
        "'web' shape: {type, url, title, quote} — quote is required; "
        "'diff' shape: {type, commit, file?, description}."
    ))],
    discussion_id: Annotated[int, Field(description="ID of the research discussion this answers. Required for advancing past the research phase (0 = not linked).")] = 0,
    summary: Annotated[str, Field(description="Optional 2-3 sentence overview shown in research lists without requiring full findings to be loaded.")] = "",
) -> dict:
    """Save research findings. Called by researcher sub-agents after investigation.

    Purpose
      Persist a research entry with one or more findings, each backed by a typed proof.
      Each finding must be independently verifiable by the prover sub-agent.

    Parameters
      topic: Short title of what was investigated.
      findings: List of {summary, details, proof} dicts. Proof must be one of three
        typed shapes: "code" (file + line range), "web" (url + quote),
        "diff" (commit + description).
      summary: Optional overview shown in research lists.
      discussion_id: Optional — link findings to the research discussion they answer.
        Required for advancing past the research phase.

    Returns
      {ok: True, research_id: int}

    Errors
      - validation: missing topic, empty findings, unknown proof type, missing required
        proof fields (e.g. 'web' proof without quote).
      - not_found: referenced discussion_id does not exist.
      - transient: DB failure.

    Example (proof types)
      code:  {type: "code", file: "x/y.py", line_start: 10, line_end: 20,
              snippet_start: 12, snippet_end: 18}
      web:   {type: "web", url: "https://...", title: "...", quote: "..."}
      diff:  {type: "diff", commit: "abc123", file?: "...", description: "..."}
    """
    result = research_service.save_research(
        db, ws, topic, findings,
        discussion_id=discussion_id if discussion_id else None,
        summary=summary,
    )
    if "error" in result:
        return mcp_error("validation", result["error"], retryable=False)
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False))
@with_mcp_workspace
def workspace_list_research(ws, project, db, locale) -> list:
    """List all research entries for the current workspace.

    Returns a compact list — one item per entry — without full findings content.
    Each item includes: id, topic, summary, findings_count, proven, created_at.

    Use workspace_get_research to retrieve full findings and proofs for specific entries.
    """
    return research_service.list_research(db, ws["id"])


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False))
@with_mcp_workspace
def workspace_get_research(
    ws, project, db, locale,
    ids: Annotated[list[int], Field(description="List of research entry IDs to fetch.", min_length=1)],
) -> list:
    """Get full research entries by IDs. Use for detailed review before proving.

    Returns complete findings with proofs for each requested ID.
    Unknown IDs are silently omitted — check the returned list length if presence matters.

    Errors
      - validation: ids list is empty.
    """
    if not ids:
        return mcp_error("validation", "ids must contain at least one entry ID.", retryable=False)

    return research_service.get_research(db, ws["id"], ids)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, destructiveHint=False))
@with_mcp_workspace
def workspace_prove_research(
    ws, project, db, locale,
    id: Annotated[int, Field(description="Research entry ID to prove or reject.")],
    is_proven: Annotated[bool, Field(description="True = mark proven. False = mark rejected with reason.")],
    reason: Annotated[str, Field(description="Why the entry was proven or rejected. Required when is_proven=False.")] = "",
) -> dict:
    """Mark a research entry as proven or rejected. Called by the prover agent after verification.

    Proving the same entry twice with the same verdict is a no-op (idempotent).

    Returns
      {ok: True, id: int, proven: bool}

    Errors
      - not_found: research entry ID does not exist in this workspace.
    """
    result = research_service.set_proven(db, id, ws["id"], is_proven, notes=reason)
    if "error" in result:
        return mcp_error(
            "not_found",
            t("mcp.error.researchEntryNotFound", locale, id=id),
            retryable=False,
        )
    db.commit()
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, destructiveHint=True))
@with_mcp_workspace
def workspace_delete_research(
    ws, project, db, locale,
    id: Annotated[int, Field(description="Research entry ID to delete.")],
) -> dict:
    """Delete a research entry. Use when findings were rejected by the prover and replaced by new research.

    Deleting an already-deleted entry is a no-op (idempotent).

    Returns
      {ok: True, deleted_id: int}

    Errors
      - not_found: research entry ID does not exist in this workspace.
    """
    deleted = research_service.delete_research(db, id, ws["id"])
    if not deleted:
        return mcp_error(
            "not_found",
            t("mcp.error.researchEntryNotFound", locale, id=id),
            retryable=False,
        )
    db.commit()
    return {"ok": True, "deleted_id": id}
