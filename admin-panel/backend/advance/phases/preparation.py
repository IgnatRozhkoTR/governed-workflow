"""Preparation workflow phases: 0 (init) through 1.4 (preparation review gate)."""
import json

from advance.phases import Phase
from core.db import get_db_ctx
from core.i18n import t


class InitPhase(Phase):
    id = "0"
    name = "Init"
    short_description = "Spawn plan-advisor"

    def description_for_skill(self, simple_planning: bool = False, workflow_mode: str = "standard") -> str:
        return """\
## 0 Init — Spawn Plan-Advisor

**Actors**: Orchestrator

The workspace already exists (created via admin panel). This phase spawns the plan-advisor as a background sub-agent.

### Steps

1. Spawn `plan-advisor` as a background sub-agent:

```
Agent(
  name: "plan-advisor",
  subagent_type: "plan-advisor",
  run_in_background: true,
  prompt: "You are the plan-advisor in this governed workflow session.
           Your role definition is the plan-advisor agent.
           Workspace: {working_dir}
           Your role: assess the codebase, advise on planning, review the execution plan.
           Wait for instructions from the orchestrator."
)
```

2. Call `workspace_advance` to move to phase 1.0.

**The plan-advisor is always reachable via `SendMessage(to: "plan-advisor", ...)`.**"""

    def validate(self, ws, body, project_path):
        return True, {}

    def next_phase(self, ws):
        return "1.0"


class AssessmentPhase(Phase):
    id = "1.0"
    name = "Assessment"
    short_description = "plan-advisor surveys the codebase and raises research topics"

    def description_for_skill(self, simple_planning: bool = False, workflow_mode: str = "standard") -> str:
        return """\
## 1.0 Assessment

**Actor**: plan-advisor (messaged — NOT a new sub-agent)

If the plan-advisor is not yet spawned (skipped Phase 0 or session recovery), spawn it first (see Phase 0 steps).

Message the plan-advisor with the structured assessment brief from `/plan-preparation`.

When assessment is complete:
1. Call `workspace_update_progress` for phase `"1.0"` with a non-empty summary
2. Call `workspace_advance`

**Advancing from 1.0** requires: progress entry `"1.0"` with a non-empty summary AND at least one open research discussion (`type='research'`)."""

    def progress_key(self, ws):
        return "1.0"

    def validate(self, ws, body, project_path):
        locale = ws["locale"]

        with get_db_ctx() as db:
            count = db.execute(
                "SELECT COUNT(*) as cnt FROM discussions "
                "WHERE workspace_id = ? AND scope IS NULL AND parent_id IS NULL AND type = 'research'",
                (ws["id"],)
            ).fetchone()["cnt"]

        if count == 0:
            return False, {"message": t("advance.error.noResearchDiscussion", locale)}

        return True, {}

    def next_phase(self, ws):
        return "1.1"


class ResearchPhase(Phase):
    id = "1.1"
    name = "Research"
    short_description = "Parallel researcher sub-agents investigate each topic"

    def description_for_skill(self, simple_planning: bool = False, workflow_mode: str = "standard") -> str:
        return """\
## 1.1 Research

**Actors**: Researcher sub-agents (parallel, one-shot)

Deploy parallel researcher sub-agents — one per investigation topic identified in assessment (researcher choice: see `/plan-preparation`). Each calls `workspace_save_research` with findings and typed proofs; the proof formats are defined in the researcher agents.

Every unresolved research discussion (raised during assessment) MUST be linked to at least one research entry before advancing.

Call `workspace_advance(no_further_research_needed=true)` when all researchers complete.

**Advancing from 1.1** requires: `no_further_research_needed=true`, every open research discussion has linked research, at least 1 research entry, all entries valid."""

    def validate(self, ws, body, project_path):
        locale = ws["locale"]
        # Check explicit confirmation
        if not body.get("no_further_research_needed"):
            return False, {"message": t("advance.error.noFurtherResearch", locale)}

        with get_db_ctx() as db:
            # Check all unresolved research discussions have linked research
            unresolved_research_discussions = db.execute(
                "SELECT id, text FROM discussions "
                "WHERE workspace_id = ? AND scope IS NULL AND parent_id IS NULL "
                "AND type = 'research' AND status = 'open'",
                (ws["id"],)
            ).fetchall()

            missing = []
            for disc in unresolved_research_discussions:
                linked = db.execute(
                    "SELECT COUNT(*) as cnt FROM research_entries "
                    "WHERE workspace_id = ? AND discussion_id = ?",
                    (ws["id"], disc["id"])
                ).fetchone()["cnt"]
                if linked == 0:
                    missing.append({"discussion_id": disc["id"], "text": disc["text"][:100]})

            if missing:
                return False, {
                    "message": t("advance.error.missingResearch", locale),
                    "missing": missing
                }

            # Existing validation: check research entries exist and are valid
            rows = db.execute(
                "SELECT id, findings_json FROM research_entries WHERE workspace_id = ?",
                (ws["id"],)
            ).fetchall()

        if not rows:
            return False, {"message": t("advance.error.noResearchEntries", locale)}

        errors = []
        for row in rows:
            try:
                findings = json.loads(row["findings_json"])
            except (json.JSONDecodeError, TypeError):
                errors.append({"entry_id": row["id"], "issues": [t("advance.error.invalidJson", locale)]})
                continue

            if not isinstance(findings, list) or not findings:
                errors.append({"entry_id": row["id"], "issues": [t("advance.error.emptyFindings", locale)]})
                continue

            entry_issues = []
            for fi, finding in enumerate(findings):
                if not isinstance(finding.get("summary"), str) or not finding.get("summary"):
                    entry_issues.append(t("advance.error.missingSummary", locale, index=fi))

                proof = finding.get("proof")
                if not isinstance(proof, dict):
                    entry_issues.append(t("advance.error.missingProof", locale, index=fi))
                    continue

                proof_type = proof.get("type", "code")
                if proof_type == "code":
                    if not proof.get("file"):
                        entry_issues.append(t("advance.error.codeProofMissingFile", locale, index=fi))
                    if not proof.get("line_start") or not proof.get("line_end"):
                        entry_issues.append(t("advance.error.codeProofMissingLineRange", locale, index=fi))
                elif proof_type == "web":
                    if not proof.get("url"):
                        entry_issues.append(t("advance.error.webProofMissingUrl", locale, index=fi))
                elif proof_type == "diff":
                    if not proof.get("commit"):
                        entry_issues.append(t("advance.error.diffProofMissingCommit", locale, index=fi))

            if entry_issues:
                errors.append({"entry_id": row["id"], "issues": entry_issues})

        if errors:
            return False, {"errors": errors}
        return True, {}

    def next_phase(self, ws):
        return "1.2"


class ProverPhase(Phase):
    id = "1.2"
    name = "Research Proving"
    short_description = "Prover sub-agent verifies every research entry"

    def description_for_skill(self, simple_planning: bool = False, workflow_mode: str = "standard") -> str:
        if workflow_mode == "fast":
            return self._fast_description()
        return self._standard_description()

    def _standard_description(self) -> str:
        return """\
## 1.2 Research Proving

**Actor**: Prover sub-agent (Opus, one-shot)

Deploy one prover sub-agent:

```
Agent(
  subagent_type: "research-prover",
  prompt: "Verify all research entries for this workspace. Mark each as proven or rejected.
           Workspace: {working_dir}"
)
```

The prover ONLY verifies — it does NOT research. It calls `workspace_prove_research` for each entry DIRECTLY — the orchestrator does NOT need to call it. Its return is the completion notice — ask it for a short proven/rejected list rather than re-reading every entry.

If any research is rejected: re-deploy the original researcher sub-agents for those topics (to fix their proofs), then re-deploy the prover.

When all research is proven (prover confirms):
1. Call `workspace_update_progress` for phase `"1"`
2. Call `workspace_advance`

**Advancing from 1.2** requires: all research entries proven (none rejected, none unproven) + progress entry `"1"`."""

    def _fast_description(self) -> str:
        return """\
## 1.2 Research Proving

**Actor**: Prover sub-agent (Opus, one-shot)

Deploy one prover sub-agent:

```
Agent(
  subagent_type: "research-prover",
  prompt: "Verify all research entries for this workspace. Mark each as proven or rejected.
           Workspace: {working_dir}"
)
```

The prover ONLY verifies — it does NOT research. It calls `workspace_prove_research` for each entry DIRECTLY — the orchestrator does NOT need to call it. Its return is the completion notice — ask it for a short proven/rejected list rather than re-reading every entry.

If any research is rejected: re-deploy the original researcher sub-agents for those topics (to fix their proofs), then re-deploy the prover.

When all research is proven (prover confirms):
1. Call `workspace_update_progress` for phase `"1"`
2. Call `workspace_advance`

**Advancing from 1.2** requires: all research entries proven (none rejected, none unproven) + progress entry `"1"`. Fast mode skips impact analysis and the preparation review gate — advancing here goes directly to planning."""

    def progress_key(self, ws):
        return "1"

    def validate(self, ws, body, project_path):
        locale = ws["locale"]
        with get_db_ctx() as db:
            rows = db.execute(
                "SELECT id, topic, proven FROM research_entries WHERE workspace_id = ?",
                (ws["id"],)
            ).fetchall()

        if not rows:
            return False, {"message": t("advance.error.noResearchToProve", locale)}

        unproven = [{"id": r["id"], "topic": r["topic"]} for r in rows if r["proven"] != 1]
        rejected = [{"id": r["id"], "topic": r["topic"]} for r in rows if r["proven"] == -1]

        if rejected:
            return False, {
                "message": t("advance.error.rejectedEntries", locale, count=len(rejected)),
                "rejected": rejected,
            }

        if unproven:
            return False, {
                "message": t("advance.error.unprovenEntries", locale, count=len(unproven)),
                "unproven": unproven,
            }

        return True, {}

    def next_phase(self, ws):
        return "1.3"


class ImpactAnalysisPhase(Phase):
    id = "1.3"
    name = "Impact Analysis"
    short_description = "Document cross-cutting effects before planning"

    def description_for_skill(self, simple_planning: bool = False, workflow_mode: str = "standard") -> str:
        return """\
## 1.3 Impact Analysis

**Actors**: Orchestrator + plan-advisor

Before planning, document the cross-cutting effects of this change, following `/plan-preparation` (advisor brief, six-field structure, research loop).

Save the result via `workspace_set_impact_analysis` with the six fields. The Pre-planning tab renders it alongside the research summaries so the user can review everything before the preparation gate.

When complete:
1. Call `workspace_update_progress` for phase `"1.3"`
2. Call `workspace_advance`

**Advancing from 1.3** requires: progress entry `"1.3"`. (Impact analysis should be populated — the user will reject at the preparation review gate if it isn't.)"""

    def progress_key(self, ws):
        return "1.3"

    def validate(self, ws, body, project_path):
        return True, {}

    def next_phase(self, ws):
        return "1.4"


class PreparationReviewPhase(Phase):
    id = "1.4"
    name = "Preparation Review"
    is_user_gate = True
    approve_target = "2.0"
    reject_target = "1.1"
    short_description = "User reviews assessment, research, and impact analysis"

    def description_for_skill(self, simple_planning: bool = False, workflow_mode: str = "standard") -> str:
        return """\
## 1.4 Preparation Review (USER GATE)

The user reviews the full preparation package in the Pre-planning tab: assessment summary, research findings, and impact analysis.

- **Approve** → the backend advances you to the next enabled phase
- **Reject** → the backend moves you back into the preparation phases with comments

**Waiting**: do not poll — see User Gates — Waiting below.

**After rejection**: follow User Gate Rejection below. Here the work is: deploy more researcher sub-agents (and update impact analysis later) to address the feedback, and re-run every preparation phase you were returned to before advancing back to the gate."""

    def progress_key(self, ws):
        return "1.3"

    def validate(self, ws, body, project_path):
        return True, {}

    def next_phase(self, ws):
        return "2.0"


PHASES = [
    InitPhase(),
    AssessmentPhase(),
    ResearchPhase(),
    ProverPhase(),
    ImpactAnalysisPhase(),
    PreparationReviewPhase(),
]
