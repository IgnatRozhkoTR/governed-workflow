"""Execution sub-phases: 3.N.0 through 3.N.4, parameterized by execution item N."""
import json
import re

from advance.phases import Phase
from advance.validators import validate_all
from core.db import get_db_ctx, ws_field
from core.helpers import workspace_dir, run_git, match_scope_pattern, DEFAULT_SOURCE_BRANCH
from core.i18n import t
from services import plan_service
from services import scope_service
from services import verification_service


def _max_execution_n(execution):
    """Return the highest sub-phase number from execution item IDs matching '3.N'."""
    max_n = 0
    for item in execution:
        m = re.match(r'^3\.(\d+)$', item.get("id", ""))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n


def _diff_files_outside_scope(ws, checkpoint: str, commit_hash: str) -> tuple[list[str], list[str]]:
    """Return (offending_files, allowed_patterns) for the commit diff.

    Compares files changed between checkpoint..commit_hash against the active
    sub-phase's must + may scope patterns. offending_files is empty when every
    changed file matches at least one pattern.
    """
    ok, stdout, _ = run_git(ws["working_dir"], "diff", "--name-only", f"{checkpoint}..{commit_hash}")
    if not ok:
        return [], []

    changed = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not changed:
        return [], []

    scope_map = json.loads(ws["scope_json"]) if ws["scope_json"] else {}
    must_patterns, may_patterns = scope_service.get_scope_patterns(scope_map, ws["phase"])
    all_patterns = list(must_patterns) + list(may_patterns)

    if not all_patterns:
        return [], []

    offending = []
    for path in changed:
        matched = False
        for pattern in all_patterns:
            match_pattern = pattern.rstrip("/") + "/**" if pattern.endswith("/") else pattern
            if match_scope_pattern(path, match_pattern):
                matched = True
                break
        if not matched:
            offending.append(path)
    return offending, all_patterns


class ImplementationPhase(Phase):
    """Execution sub-phase K=0: implementation."""
    name = "Implementation"

    def __init__(self, n):
        self._n = n

    @property
    def id(self):
        return f"3.{self._n}.0"

    def validate(self, ws, body, project_path):
        scope_map = json.loads(ws["scope_json"]) if ws["scope_json"] else {}
        phase = ws["phase"]
        must_patterns = scope_service.get_phase_must_patterns(scope_map, phase)

        if not must_patterns:
            return True, {}

        try:
            source = ws["source_branch"] or DEFAULT_SOURCE_BRANCH
        except (IndexError, KeyError):
            source = DEFAULT_SOURCE_BRANCH

        all_changed = set()

        ok, stdout, _ = run_git(ws["working_dir"], "diff", "--name-only", f"{source}..HEAD")
        if not ok:
            ok, stdout, _ = run_git(ws["working_dir"], "diff", "--name-only", f"origin/{source}..HEAD")
        if not ok:
            ok, stdout, _ = run_git(ws["working_dir"], "diff", "--name-only", "HEAD")
        if ok:
            all_changed.update(line.strip() for line in stdout.splitlines() if line.strip())

        ok2, stdout2, _ = run_git(ws["working_dir"], "diff", "--cached", "--name-only")
        if ok2:
            all_changed.update(line.strip() for line in stdout2.splitlines() if line.strip())

        # Unstaged modifications to tracked files
        ok2b, stdout2b, _ = run_git(ws["working_dir"], "diff", "--name-only")
        if ok2b:
            all_changed.update(line.strip() for line in stdout2b.splitlines() if line.strip())

        ok3, stdout3, _ = run_git(ws["working_dir"], "ls-files", "--others", "--exclude-standard")
        if ok3:
            all_changed.update(line.strip() for line in stdout3.splitlines() if line.strip())

        changed_files = list(all_changed)

        for pattern in must_patterns:
            matched = False
            for changed_file in changed_files:
                if pattern.endswith("/"):
                    match_pattern = pattern.rstrip("/") + "/**"
                else:
                    match_pattern = pattern
                if match_scope_pattern(changed_file, match_pattern):
                    matched = True
                    break
            if not matched:
                return False, {"message": t("advance.error.noMustScopeChanges", ws["locale"], pattern=pattern)}

        return True, {}

    def next_phase(self, ws):
        return f"3.{self._n}.1"


class VerificationPhase(Phase):
    """Execution sub-phase K=1: verification."""
    name = "Verification"

    def __init__(self, n):
        self._n = n
        self._project_path = None

    @property
    def id(self):
        return f"3.{self._n}.1"

    def validate(self, ws, body, project_path):
        """Run verification profiles at validation phase. Blocks advance if any blocking step fails."""
        self._project_path = project_path
        phase = f"3.{self._n}.1"
        with get_db_ctx() as db:
            passed, run_id = verification_service.run_verification(
                db, ws["id"], phase, ws["working_dir"]
            )
            db.commit()
            if not passed:
                return False, {
                    "message": f"Verification failed (run_id={run_id}). Check verification results in the admin panel and fix the issues before advancing."
                }
            return True, {}

    def next_phase(self, ws):
        """Route after validation based on agent results and legacy file."""
        n = self._n
        phase = f"3.{n}.1"

        # Check agent validation results (submitted via workspace_submit_validation)
        with get_db_ctx() as db:
            agent_result = verification_service.get_verification_results(db, ws["id"], phase=phase)
            if agent_result and agent_result.get("status") == "failed":
                return f"3.{n}.2"

        # Fallback: check legacy file-based validation (skipped in yolo mode where _project_path is None)
        if self._project_path is None:
            return f"3.{n}.3"
        ws_dir = workspace_dir(self._project_path, ws["branch"])
        validation_path = ws_dir / "validation" / f"3.{n}.json"
        if validation_path.exists():
            try:
                data = json.loads(validation_path.read_text())
                if data.get("status") == "clean":
                    return f"3.{n}.3"
            except (json.JSONDecodeError, OSError):
                pass
            return f"3.{n}.2"

        # No validation data -- default to clean
        return f"3.{n}.3"


class FixReviewPhase(Phase):
    """Execution sub-phase K=2: fix review after failed verification."""
    name = "Fix Review"

    def __init__(self, n):
        self._n = n

    @property
    def id(self):
        return f"3.{self._n}.2"

    def validate(self, ws, body, project_path):
        return True, {}

    def next_phase(self, ws):
        return f"3.{self._n}.3"


class CommitApprovalPhase(Phase):
    """Execution sub-phase K=3: user gate for commit approval."""
    name = "Commit Approval"
    is_user_gate = True

    def __init__(self, n):
        self._n = n

    @property
    def id(self):
        return f"3.{self._n}.3"

    @property
    def approve_target(self):
        return f"3.{self._n}.4"

    @property
    def reject_target(self):
        return f"3.{self._n}.2"

    def on_approve(self, ws, body, db):
        commit_message = body.get("commit_message") if body else None
        if commit_message:
            db.execute(
                "UPDATE workspaces SET commit_message = ? WHERE id = ?",
                (commit_message, ws["id"])
            )

    def validate(self, ws, body, project_path):
        return True, {}

    def next_phase(self, ws):
        return f"3.{self._n}.4"


class CommitPhase(Phase):
    """Execution sub-phase K=4: commit validation and transition."""
    name = "Commit"

    def __init__(self, n):
        self._n = n

    @property
    def id(self):
        return f"3.{self._n}.4"

    def progress_key(self, ws):
        return f"3.{self._n}"

    def validate(self, ws, body, project_path):
        """Validate the submitted commit for this commit sub-phase.

        Runs, in order:
        1. Basic commit presence + existence + phase_history replay guard.
        2. Commit progression checks (HEAD match, forward-only checkpoint,
           scope-bounded diff) via ``_validate_commit_progression``.
        3. Acceptance-criteria validation on the final sub-phase.

        All checks are gated by ``perform_advance``'s ``if not yolo_mode:``
        block, so yolo mode bypasses them by not calling ``validate`` at all.
        """
        locale = ws["locale"]
        commit_hash = body.get("commit_hash", "")
        if not commit_hash:
            return False, {"message": t("advance.error.commitHashRequired", locale)}

        ok, _, _ = run_git(ws["working_dir"], "cat-file", "-t", commit_hash)
        if not ok:
            return False, {"message": t("advance.error.commitNotFound", locale, commit_hash=commit_hash)}

        with get_db_ctx() as db:
            used = db.execute(
                "SELECT id FROM phase_history WHERE workspace_id = ? AND commit_hash = ?",
                (ws["id"], commit_hash)
            ).fetchone()
        if used:
            return False, {"message": t("advance.error.commitAlreadyUsed", locale, commit_hash=commit_hash)}

        progression_ok, progression_details = self._validate_commit_progression(ws, commit_hash)
        if not progression_ok:
            return False, progression_details

        plan = plan_service.get_plan(ws)
        max_n = _max_execution_n(plan.get("execution", []))

        if self._n >= max_n:
            with get_db_ctx() as db:
                all_passed, results = validate_all(db, ws["id"], ws["working_dir"])
                db.commit()

            if not all_passed:
                failed = [r for r in results if not r["passed"]]
                messages = [f"  - {r['type']}: {r['message']}" for r in failed]
                return False, {
                    "message": t("advance.error.acceptanceCriteriaNotMet", locale, messages="\n".join(messages))
                }

        return True, {}

    def _validate_commit_progression(self, ws, commit_hash: str) -> tuple[bool, dict]:
        """Enforce HEAD match, forward-only checkpoint, and scope-bounded diff.

        Legacy workspaces that entered 3.N.4 before lazy init was introduced
        may still have ``last_confirmed_commit = NULL``. In that case, fall
        back to ``commit_hash^`` (the parent) and persist it so subsequent
        checks have a stable base.
        """
        locale = ws["locale"]
        working_dir = ws["working_dir"]

        ok, stdout, _ = run_git(working_dir, "rev-parse", "HEAD")
        if not ok:
            return False, {"message": t("advance.error.commitNotFound", locale, commit_hash=commit_hash)}
        head = stdout.strip()
        if head != commit_hash:
            return False, {"message": t("advance.error.commitNotHead", locale, commit_hash=commit_hash, head=head)}

        checkpoint = ws_field(ws, "last_confirmed_commit", None)
        if not checkpoint:
            ok_parent, parent_stdout, _ = run_git(working_dir, "rev-parse", f"{commit_hash}^")
            if not ok_parent or not parent_stdout.strip():
                return False, {"message": t("advance.error.commitNotDescendant", locale)}
            checkpoint = parent_stdout.strip()
            with get_db_ctx() as db:
                db.execute(
                    "UPDATE workspaces SET last_confirmed_commit = ? WHERE id = ?",
                    (checkpoint, ws["id"])
                )
                db.commit()

        if checkpoint == commit_hash:
            return False, {"message": t("advance.error.commitNoForwardProgress", locale)}

        ancestor_ok, _, _ = run_git(working_dir, "merge-base", "--is-ancestor", checkpoint, commit_hash)
        if not ancestor_ok:
            return False, {"message": t("advance.error.commitNotDescendant", locale)}

        offending, allowed_patterns = _diff_files_outside_scope(ws, checkpoint, commit_hash)
        if offending:
            shown = offending[:5]
            files_str = "\n".join(f"  - {f}" for f in shown)
            if len(offending) > len(shown):
                files_str += f"\n  ... and {len(offending) - len(shown)} more"
            patterns_str = "\n".join(f"  - {p}" for p in allowed_patterns) if allowed_patterns else "  (none)"
            return False, {
                "message": t(
                    "advance.error.commitDiffOutsideScope", locale,
                    files=files_str, patterns=patterns_str,
                )
            }

        return True, {}

    def next_phase(self, ws):
        n = self._n
        plan = plan_service.get_plan(ws)
        max_n = _max_execution_n(plan.get("execution", []))

        if n >= max_n:
            return "4.0"
        return f"3.{n + 1}.0"


def get_execution_phase(n: int, k: int) -> Phase | None:
    """Factory for execution phases."""
    classes = {
        0: ImplementationPhase,
        1: VerificationPhase,
        2: FixReviewPhase,
        3: CommitApprovalPhase,
        4: CommitPhase,
    }
    cls = classes.get(k)
    return cls(n) if cls else None


_TEMPLATE_NAMES = {
    0: "Implementation",
    1: "Verification",
    2: "Fix Review",
    3: "Commit Approval",
    4: "Commit",
}

_TEMPLATE_GATE_STEPS = frozenset({3})


class _ExecutionTemplatePhase(Phase):
    """Structural placeholder for an execution sub-step parameterized by item.

    Template phases exist only so the registry can describe the execution
    sub-step family. They are expanded into concrete ``3.N.K`` phases at
    sequence time; any attempt to execute a template directly is a bug.
    """

    def __init__(self, k: int):
        self._k = k

    @property
    def id(self) -> str:
        return f"3.x.{self._k}"

    @property
    def name(self) -> str:
        return _TEMPLATE_NAMES[self._k]

    @property
    def is_user_gate(self) -> bool:
        return self._k in _TEMPLATE_GATE_STEPS

    def validate(self, ws, body, project_path):
        raise NotImplementedError(
            "template phase; call get_execution_phase(N, K) to instantiate"
        )

    def next_phase(self, ws):
        raise NotImplementedError(
            "template phase; call get_execution_phase(N, K) to instantiate"
        )


def _register_execution_templates() -> None:
    """Register the five execution-step templates into the shared registry."""
    from advance.phases import register_phase

    for k in _TEMPLATE_NAMES:
        register_phase(_ExecutionTemplatePhase(k))


_register_execution_templates()
