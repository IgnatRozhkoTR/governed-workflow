"""MCP stdio server — governed workflow admin panel.

All tool implementations live in mcp_tools/.
Importing mcp_tools triggers @mcp.tool registration for all tools.
"""
from advance.phases import register_module_phases_from_disk
from mcp_tools import mcp, _detect_workspace
from mcp_tools.state import workspace_get_state
from mcp_tools.advance import workspace_advance
from mcp_tools.plan_scope import (
    workspace_set_plan,
    workspace_get_plan,
    workspace_extend_plan,
    workspace_update_subphase,
    workspace_delete_subphase,
    workspace_set_plan_diagrams,
    workspace_set_plan_description,
)
from mcp_tools.research import (
    workspace_post_discussion,
    workspace_save_research,
    workspace_list_research,
    workspace_get_research,
    workspace_prove_research,
    workspace_delete_research,
)
from mcp_tools.comments import (
    workspace_get_comments,
    workspace_post_comment,
    workspace_resolve_comment,
    workspace_submit_review_issue,
    workspace_get_review_issues,
    workspace_resolve_review_issue,
)
from mcp_tools.progress import (
    workspace_set_impact_analysis,
    workspace_update_progress,
    workspace_get_progress,
)
from mcp_tools.criteria import (
    workspace_propose_criteria,
    workspace_get_criteria,
    workspace_update_criteria,
    workspace_delete_criteria,
)
from mcp_tools.verification import (
    workspace_get_verification_results,
    workspace_get_verification_profiles,
    workspace_create_verification_profile,
    workspace_update_verification_profile,
    workspace_add_verification_step,
    workspace_assign_verification_profile,
)
from mcp_tools.rules import (
    rule_list,
    rule_get,
    rule_create,
    rule_update,
    rule_delete,
)
from mcp_tools.review_pipeline import workspace_review_pipeline_summary
from mcp_tools.proposals import (
    workspace_submit_proposal,
    workspace_get_reflection_context,
    workspace_list_proposals,
    workspace_resolve_proposal,
)

_SIMPLE_MODE_HIDDEN_TOOLS = (
    "workspace_propose_criteria",
    "workspace_update_criteria",
    "workspace_get_criteria",
    "workspace_delete_criteria",
    "workspace_extend_plan",
    "workspace_update_subphase",
    "workspace_delete_subphase",
    "workspace_set_plan_diagrams",
)


def _deregister_simple_mode_tools() -> None:
    """Remove simple-planning-incompatible tools from the FastMCP registry.

    This is a best-effort optimisation — the runtime guards in each tool handler
    are the actual enforcement. If detection fails the server still starts normally.
    """
    import logging

    log = logging.getLogger(__name__)
    try:
        ws, project = _detect_workspace()
        if project is None or not project["simple_planning"]:
            return
        for tool_name in _SIMPLE_MODE_HIDDEN_TOOLS:
            try:
                mcp.remove_tool(tool_name)
                log.info("Simple planning mode: deregistered tool %s", tool_name)
            except Exception:
                log.info(
                    "Simple planning mode: could not deregister %s; runtime guards remain active",
                    tool_name,
                )
    except Exception:
        log.info(
            "Simple planning mode tool-hiding: workspace detection failed; "
            "runtime guards remain active"
        )


if __name__ == "__main__":
    register_module_phases_from_disk()
    _deregister_simple_mode_tools()
    mcp.run(transport="stdio")
