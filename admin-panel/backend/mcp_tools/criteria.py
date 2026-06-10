from typing import Annotated, Literal, Optional

from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tools import mcp, with_mcp_workspace, mcp_error
from core.helpers import VALID_CRITERIA_TYPES
from core.i18n import t
from core.phase import phase_key
from services import criteria_service

_CRITERIA_TYPE = Literal["unit_test", "integration_test", "bdd_scenario", "custom"]
_CRITERIA_STATUS = Literal["proposed", "accepted", "rejected"]


def _criteria_update_error_mapping(criterion_id, locale):
    return {
        "criterion_not_found": (
            "not_found",
            False,
            t("mcp.error.criterionNotFound", locale, criterion_id=criterion_id),
        ),
        "cannot_update_accepted": (
            "business",
            False,
            t("mcp.error.cannotUpdateAcceptedCriteria", locale),
        ),
        "nothing_to_update": (
            "validation",
            False,
            t("mcp.error.nothingToUpdate", locale),
        ),
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title="Propose acceptance criterion",
        readOnlyHint=False,
        idempotentHint=False,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def workspace_propose_criteria(
    ws,
    project,
    db,
    locale,
    type: Annotated[
        _CRITERIA_TYPE,
        Field(description="Kind of acceptance criterion this is."),
    ],
    description: Annotated[
        str,
        Field(description="Human-readable description of what must pass.", min_length=1),
    ],
    details_json: Annotated[
        str,
        Field(
            description=(
                "JSON string with type-specific fields. "
                "unit_test/integration_test: {\"file\": \"path/to/TestFile.java\", \"test_names\": [...]}. "
                "bdd_scenario: {\"file\": \"features/file.feature\", \"scenario_names\": [...]}. "
                "custom: {\"instruction\": \"what to verify\"}. "
                "All types accept optional \"verification_command\" (exit 0 = pass)."
            )
        ),
    ] = "",
) -> dict:
    """Propose an acceptance criterion for the workspace.

    Purpose
      Called by the agent during planning (phase 2.0+) to suggest a verifiable
      criterion. Each call creates a new criterion record with status='proposed'.
      Approving the plan accepts all proposed criteria in one action.

    Parameters
      type: Criterion kind — unit_test, integration_test, bdd_scenario, custom.
      description: Human-readable statement of what must pass.
      details_json: JSON object with type-specific fields (see param description).

    Returns
      {ok: True, criterion: {id, type, description, details, status, source}}

    Errors
      validation — proposed before phase 2.0, type not in allowed set,
                   details_json not valid JSON or not an object.

    Example
      workspace_propose_criteria(type="unit_test",
          description="UserService.createUser saves to DB",
          details_json='{"file": "tests/UserServiceTest.java", "test_names": ["createUser_shouldPersist"]}')
    """
    if project["simple_planning"]:
        return mcp_error(
            "business",
            "Acceptance criteria are not used in simple planning mode.",
            retryable=False,
        )

    if phase_key(ws["phase"]) < phase_key("2.0"):
        return mcp_error(
            "validation",
            t("mcp.error.criteriaPhase", locale),
            retryable=False,
        )

    if type not in VALID_CRITERIA_TYPES:
        return mcp_error(
            "validation",
            t("mcp.error.invalidCriteriaType", locale, type=type, valid_types=", ".join(VALID_CRITERIA_TYPES)),
            retryable=False,
        )

    result = criteria_service.propose_criterion(
        db, ws["id"], type, description, details_json=details_json or None, source="agent"
    )
    if "error" in result:
        return mcp_error("validation", result["error"], retryable=False)
    db.commit()
    return result


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get acceptance criteria",
        readOnlyHint=True,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def workspace_get_criteria(
    ws,
    project,
    db,
    locale,
    status: Annotated[
        Optional[_CRITERIA_STATUS],
        Field(description="Filter by status. Omit or pass None to return all."),
    ] = None,
    type: Annotated[
        Optional[_CRITERIA_TYPE],
        Field(description="Filter by criterion kind. Omit or pass None to return all."),
    ] = None,
) -> list:
    """Get acceptance criteria for the current workspace.

    Purpose
      Returns criteria records, optionally narrowed by status and/or type.
      An empty list means no criteria match the filter — not an error.
      Use workspace_propose_criteria to add new criteria.

    Parameters
      status: proposed | accepted | rejected. None returns all statuses.
      type: unit_test | integration_test | bdd_scenario | custom. None returns all types.

    Returns
      List of {id, type, description, details, source, status, validated, validation_message}.

    Example
      workspace_get_criteria()
      workspace_get_criteria(status="proposed")
      workspace_get_criteria(type="unit_test", status="accepted")
    """
    if project["simple_planning"]:
        return mcp_error(
            "business",
            "Acceptance criteria are not used in simple planning mode.",
            retryable=False,
        )

    return criteria_service.get_criteria(
        db, ws["id"], status=status or None, criterion_type=type or None
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Update acceptance criterion",
        readOnlyHint=False,
        idempotentHint=True,
        destructiveHint=False,
    )
)
@with_mcp_workspace
def workspace_update_criteria(
    ws,
    project,
    db,
    locale,
    criterion_id: Annotated[
        int,
        Field(description="Numeric ID returned by workspace_propose_criteria.", ge=1),
    ],
    description: Annotated[
        str,
        Field(description="Updated human-readable description. Omit or pass empty to keep existing."),
    ] = "",
    details_json: Annotated[
        str,
        Field(
            description=(
                "Updated details as a JSON string. Omit or pass empty to keep existing. "
                "unit_test/integration_test: {\"file\": \"...\", \"test_names\": [...]}. "
                "bdd_scenario: {\"file\": \"...\", \"scenario_names\": [...]}. "
                "custom: {\"instruction\": \"...\"}."
            )
        ),
    ] = "",
) -> dict:
    """Update an existing acceptance criterion's description and/or details.

    Purpose
      Use this to fill in file paths, test names, and refined descriptions —
      typically for criteria initially created by the user with incomplete details.
      Calling with the same values is a no-op (returns nothing_to_update error).
      Accepted criteria cannot be modified.

    Parameters
      criterion_id: ID of the criterion to update (from propose_criteria response).
      description: Replacement description. Empty = keep current.
      details_json: Replacement details JSON. Empty = keep current.

    Returns
      {ok: True, id, criterion: {...}, warnings?: [...]}

    Errors
      not_found  — criterion_id does not exist in this workspace.
      business   — criterion has been accepted and cannot be changed.
      validation — nothing to update, or details_json is malformed / not an object.

    Example
      workspace_update_criteria(criterion_id=3,
          details_json='{"file": "tests/UserTest.java", "test_names": ["testCreate"]}')
    """
    if project["simple_planning"]:
        return mcp_error(
            "business",
            "Acceptance criteria are not used in simple planning mode.",
            retryable=False,
        )

    result = criteria_service.update_criterion(
        db, criterion_id, ws["id"],
        description=description or None, details_json=details_json or None
    )
    if "error" in result:
        error_key = result["error"]
        localized_mapping = _criteria_update_error_mapping(criterion_id, locale)
        if error_key in localized_mapping:
            category, retryable, message = localized_mapping[error_key]
            return mcp_error(category, message, retryable=retryable)
        return mcp_error(
            "business",
            error_key,
            retryable=False,
            details={"rawCode": error_key},
        )
    db.commit()
    return result
