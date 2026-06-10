from typing import Annotated, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import mcp, with_mcp_workspace, envelope_from_status


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
        title="Advance workflow phase",
    )
)
@with_mcp_workspace
def workspace_advance(
    ws,
    project,
    db,
    locale,
    commit_hash: Annotated[
        Optional[str],
        Field(
            description=(
                "Git commit hash to record as the artifact of the completing phase. "
                "Required for commit sub-phases (3.N.4); ignored elsewhere. "
                "Pass None when advancing from non-commit phases."
            )
        ),
    ] = None,
    no_further_research_needed: Annotated[
        bool,
        Field(
            description=(
                "Must be True when advancing from phase 1.1 (Research) → 1.2 (Proving). "
                "Confirms the orchestrator has gathered enough evidence to proceed. "
                "Ignored at other phases."
            )
        ),
    ] = False,
) -> dict:
    """Request phase advancement.

    Purpose
      Advance the governed-workflow phase after completing the current phase's work.
      User gates (1.4, 3.N.3, 4.2) block advancement until the user approves in the
      admin panel — the tool returns statusCode=202 for those cases, not an error.

      At phase 1.1 (research → proving), you MUST set no_further_research_needed=True to confirm
      you have gathered all necessary information. If you're unsure, review your research findings
      against the research discussions — post new discussions and run more research if gaps exist.

      When the user REJECTS at a gate, phase reverts to the previous step (e.g. 3.N.3 → 3.N.2).
      Read user comments via workspace_get_comments, fix the issues, then call workspace_advance
      to return to the gate for re-review. Do NOT ask the user to approve in order to fix — fix
      first, then re-submit.

    Parameters
      commit_hash: Git SHA to attach to the phase (commit sub-phases only).
      no_further_research_needed: Required True at phase 1.1 → 1.2 transition.

    Returns
      Success dict with: phase, previous_phase, status, statusCode (int), message?

    Errors
      Known errors are returned as an envelope: {error, errorCategory, isRetryable, ...}.
      errorCategory values used here:
        - business        phase gate blocks advance (e.g. missing progress entry, no enabled successor)
        - validation      malformed input or guard failure (e.g. bad commit_hash shape, validate() False)
        - not_found       workspace or phase missing
        - transient       DB contention — caller should retry
      Unexpected exceptions propagate as protocol-level isError=True.

    Example
      workspace_advance()
      workspace_advance(commit_hash="a1b2c3d")
      workspace_advance(no_further_research_needed=True)
    """
    from advance.orchestrator import perform_advance

    body = {}
    if commit_hash:
        body["commit_hash"] = commit_hash
    if no_further_research_needed:
        body["no_further_research_needed"] = True

    result, code = perform_advance(ws, project["path"], body)

    if "error" in result:
        return envelope_from_status(result, code)

    return {**result, "statusCode": code}
