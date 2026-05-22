"""Preparation workflow phases: 0 (init) through 1.4 (preparation review gate)."""
import json

from advance.phases import Phase
from core.db import get_db_ctx
from core.i18n import t


class InitPhase(Phase):
    id = "0"
    name = "Init"

    def description_for_skill(self) -> str:
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

    def description_for_skill(self) -> str:
        return """\
## 1.0 Assessment

**Actor**: plan-advisor (messaged — NOT a new sub-agent)

If the plan-advisor is not yet spawned (skipped Phase 0 or session recovery), spawn it first (see Phase 0 steps).

Message the plan-advisor teammate:

```
SendMessage(
  to: "plan-advisor",
  content: "Begin assessment. Read workspace_get_state for context (ticket, working_dir, context notes).
            Identify affected areas of the codebase. Raise research questions via
            workspace_post_discussion (type='research'). Report findings in a structured summary."
)
```

When assessment is complete:
1. Propose acceptance criteria via `workspace_propose_criteria` (unit tests, integration tests, BDD scenarios, custom checks). Users accept or reject them in the admin panel.
2. Call `workspace_update_progress` for phase `"1.0"` with a non-empty summary
3. Call `workspace_advance`

**Advance 1.0 → 1.1** requires: at least one open research discussion (`type='research'`)."""

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

    def description_for_skill(self) -> str:
        return """\
## 1.1 Research

**Actors**: Researcher sub-agents (parallel, one-shot)

Deploy parallel researcher sub-agents — one per investigation topic identified in assessment. Each sub-agent:
- Investigates its topic
- Calls `workspace_save_research` with findings + typed proofs
- Each finding must include a `proof` with a `type` field. The proof format depends on the researcher type:

**type: "code"** (code-researcher, senior-code-researcher)
  - `file` — path relative to workspace root
  - `line_start`, `line_end` — PRECISE proof range. Try to stay under 20-30 lines, no hard limit.
  - `snippet_start`, `snippet_end` — 15-line max window WITHIN the proof range for the quick-reference quote
  - Do NOT include snippet text — the server reads the actual file to render quotes

**type: "web"** (web-researcher)
  - `url` — source URL (required)
  - `title` — page/article title
  - `quote` — verbatim text from the source (required — server cannot fetch web pages)

**type: "diff"** (diff-researcher)
  - `commit` — commit hash (required)
  - `file` — specific file in the commit (optional)
  - `description` — mandatory context explaining what the diff proves

Every unresolved research discussion (raised in 1.0) MUST be linked to at least one research entry before advancing.

Call `workspace_advance(no_further_research_needed=true)` when all researchers complete.

**Advance 1.1 → 1.2** requires: `no_further_research_needed=true`, every open research discussion has linked research, at least 1 research entry, all entries valid."""

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

    def description_for_skill(self) -> str:
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

The prover ONLY verifies — it does NOT research. It calls `workspace_prove_research` for each entry DIRECTLY — the orchestrator does NOT need to call it. Wait for the prover to finish, then check results.

If any research is rejected: re-deploy the original researcher sub-agents for those topics (to fix their proofs), then re-deploy the prover.

When all research is proven (prover confirms):
1. Call `workspace_update_progress` for phase `"1"`
2. Call `workspace_advance`

**Advance 1.2 → 1.3** requires: all research entries proven (none rejected, none unproven) + progress entry `"1"`."""

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

    def description_for_skill(self) -> str:
        return """\
## 1.3 Impact Analysis

**Actors**: Orchestrator + plan-advisor

Before planning, document the cross-cutting effects of this change. Message the plan-advisor:

```
SendMessage(
  to: "plan-advisor",
  content: "We are in Phase 1.3 (Impact Analysis). Using the proven research, help me
            produce a structured impact analysis covering: affected flows, API changes,
            data flow, dependencies, ticket gaps, outstanding questions."
)
```

Save the result via `workspace_set_impact_analysis` with the six fields. The Pre-planning tab renders it alongside the research summaries so the user can review everything before the preparation gate.

When complete:
1. Call `workspace_update_progress` for phase `"1.3"`
2. Call `workspace_advance`

**Advance 1.3 → 1.4** requires: progress entry `"1.3"`. (Impact analysis should be populated — user will reject at 1.4 if it isn't.)"""

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

    def description_for_skill(self) -> str:
        return """\
## 1.4 Preparation Review (USER GATE)

The user reviews the full preparation package in the Pre-planning tab: assessment summary, research findings, impact analysis, proposed acceptance criteria.

- **Approve** → advances to `2.0`
- **Reject** → back to `1.1` with comments

Poll `workspace_get_state` once per minute. After 10 polls, ask user in chat.

**After rejection**: the backend sets the phase to `1.1`. Do NOT call `workspace_advance` immediately. Instead:
1. Call `workspace_get_state` to confirm you're at `1.1`
2. Call `workspace_get_comments` to read the rejection feedback
3. Deploy more researcher sub-agents (and update impact analysis later) to address the feedback
4. Re-run Phase 1.2 and 1.3 before returning to the gate"""

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
