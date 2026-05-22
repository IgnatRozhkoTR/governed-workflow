"""Headless review pipeline for phase 4.0 blind review.

Triggered as a background thread by ``transition_phase`` when a workspace
enters phase ``4.0``. The pipeline:

1. Resolves the reviewable file list via :mod:`services.diff_filter`.
2. Fans out one ``claude -p --agent file-reviewer`` subprocess per file,
   capped by ``GOVERNED_WORKFLOW_REVIEW_CONCURRENCY`` (default 8). Each
   per-file agent returns JSON ``{file, findings: [...]}`` on stdout; the
   findings are written to the discussions table via
   :func:`services.comment_service.submit_review_issue`. The file stage
   is spawned with ``--strict-mcp-config`` so the haiku-class agent never
   loads the workspace's full MCP tool schema (which would burn opus-class
   cache-creation tokens per invocation).
3. Runs the two integration reviewers in parallel via ``asyncio.gather``:
   - ``architecture-reviewer`` — architecture + clean code + SOLID
     (SRP/OCP, layer boundaries, naming, method/class size, DRY, code smells).
   - ``correctness-reviewer`` — business-logic correctness + edge cases +
     error handling + security (input validation, injection, auth/authz,
     secrets, sensitive data in logs, API contract leaks).
   Each one self-submits findings through MCP, so the pipeline only awaits
   their exit codes. A failure in one does not cancel the other — each
   agent is wrapped in its own try/except and its error is captured on the
   in-memory ``PipelineStatus``.

Agent failures (timeout, non-zero exit, JSON parse failure) are surfaced
only via the in-memory ``PipelineStatus`` and the
``/api/workspaces/<id>/review-pipeline/summary`` endpoint — never written to
the discussions table, so the review queue stays clean. The pipeline never
raises out to the caller.

Status is exposed via :func:`get_status` (in-memory, keyed by
``workspace_id``) and the ``/api/workspaces/<id>/review-pipeline-status``
HTTP endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from core.db import get_db
from services import diff_filter
from services.comment_service import submit_review_issue

log = logging.getLogger(__name__)

_DEFAULT_CONCURRENCY = 8
_DEFAULT_TIMEOUT_S = 300
_INTEGRATION_TIMEOUT_MULTIPLIER = 3

_FILE_REVIEWER_AGENT = "file-reviewer"
_INTEGRATION_AGENTS: tuple[str, ...] = (
    "architecture-reviewer",
    "correctness-reviewer",
)
_SELF_SUBMITTING_AGENTS: frozenset[str] = frozenset({
    "architecture-reviewer",
    "correctness-reviewer",
})

_STDERR_EXCERPT_CHARS = 500

PipelineState = Literal[
    "queued", "filtering", "file_stage", "integration_stage", "done", "failed"
]
FileState = Literal["pending", "running", "done", "failed"]
AgentState = Literal["pending", "running", "done", "failed"]


def _concurrency() -> int:
    raw = os.environ.get("GOVERNED_WORKFLOW_REVIEW_CONCURRENCY")
    if raw is None:
        return _DEFAULT_CONCURRENCY
    try:
        return max(1, int(raw))
    except ValueError:
        log.warning("invalid GOVERNED_WORKFLOW_REVIEW_CONCURRENCY=%r; using default", raw)
        return _DEFAULT_CONCURRENCY


def _timeout_s() -> int:
    raw = os.environ.get("GOVERNED_WORKFLOW_REVIEW_TIMEOUT_S")
    if raw is None:
        return _DEFAULT_TIMEOUT_S
    try:
        return max(30, int(raw))
    except ValueError:
        log.warning("invalid GOVERNED_WORKFLOW_REVIEW_TIMEOUT_S=%r; using default", raw)
        return _DEFAULT_TIMEOUT_S


@dataclass
class FileResult:
    file: str
    status: FileState = "pending"
    findings_count: int = 0
    submit_failures: int = 0
    error: str | None = None


@dataclass
class PipelineStatus:
    workspace_id: int
    state: PipelineState = "queued"
    files: dict[str, FileResult] = field(default_factory=dict)
    integration: dict[str, AgentState] = field(default_factory=dict)
    integration_errors: dict[str, str] = field(default_factory=dict)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None


_STATUS: dict[int, PipelineStatus] = {}
_STATUS_LOCK = threading.Lock()


def get_status(workspace_id: int) -> PipelineStatus | None:
    with _STATUS_LOCK:
        return _STATUS.get(workspace_id)


def status_as_dict(workspace_id: int) -> dict | None:
    status = get_status(workspace_id)
    if status is None:
        return None
    return asdict(status)


_TERMINAL_STATES: frozenset[PipelineState] = frozenset({"done", "failed"})


def status_summary(workspace_id: int) -> dict | None:
    """Return a flat completion summary for the orchestrator/UI.

    Distinct from :func:`status_as_dict` (the full detail dump). Aggregates
    per-file and per-integration-agent counts so callers can make an
    advance/retry decision without walking the nested dict.

    Returns ``None`` if no run is tracked for this workspace.
    """
    status = get_status(workspace_id)
    if status is None:
        return None

    file_states = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    failed_files: list[str] = []
    failed_files_errors: dict[str, str] = {}
    files_with_findings = 0
    for path, result in status.files.items():
        file_states[result.status] = file_states.get(result.status, 0) + 1
        if result.status == "failed":
            failed_files.append(path)
            if result.error:
                failed_files_errors[path] = result.error
        if result.findings_count > 0:
            files_with_findings += 1

    integ_states = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    for agent_state in status.integration.values():
        integ_states[agent_state] = integ_states.get(agent_state, 0) + 1

    is_complete = status.state in _TERMINAL_STATES
    is_ok = (
        status.state == "done"
        and file_states["failed"] == 0
        and integ_states["failed"] == 0
    )

    return {
        "workspace_id": workspace_id,
        "state": status.state,
        "files_total": len(status.files),
        "files_done": file_states["done"],
        "files_failed": file_states["failed"],
        "files_in_progress": file_states["pending"] + file_states["running"],
        "files_with_findings": files_with_findings,
        "files_clean": file_states["done"] - files_with_findings,
        "failed_files": failed_files,
        "failed_files_errors": failed_files_errors,
        "integration_done": integ_states["done"],
        "integration_failed": integ_states["failed"],
        "integration_total": len(status.integration),
        "integration_errors": dict(status.integration_errors),
        "is_complete": is_complete,
        "is_ok": is_ok,
        "error": status.error,
        "started_at": status.started_at,
        "finished_at": status.finished_at,
    }


def _set_status(status: PipelineStatus) -> None:
    with _STATUS_LOCK:
        _STATUS[status.workspace_id] = status


_IN_PROGRESS_STATES: frozenset[PipelineState] = frozenset(
    {"queued", "filtering", "file_stage", "integration_stage"}
)


def start_in_background(
    workspace_id: int,
    project_path: Path,
    base_branch: str = "main",
) -> threading.Thread | None:
    """Start the pipeline in a daemon thread and return it.

    Flask is synchronous; ``asyncio.create_task`` cannot be used from a
    request handler. The thread owns its own DB connection (Sqlite handles
    are not thread-safe across threads) and its own asyncio event loop.

    Returns ``None`` if the pipeline is already running for this workspace.
    """
    with _STATUS_LOCK:
        existing = _STATUS.get(workspace_id)
        if existing is not None and existing.state in _IN_PROGRESS_STATES:
            log.warning(
                "review pipeline for workspace %s is already in state %r; skipping duplicate start",
                workspace_id,
                existing.state,
            )
            return None

    status = PipelineStatus(workspace_id=workspace_id, started_at=time.time())
    _set_status(status)

    thread = threading.Thread(
        target=_run_thread,
        args=(workspace_id, project_path, base_branch, status),
        name=f"review-pipeline-ws-{workspace_id}",
        daemon=True,
    )
    thread.start()
    return thread


def _run_thread(
    workspace_id: int,
    project_path: Path,
    base_branch: str,
    status: PipelineStatus,
) -> None:
    try:
        asyncio.run(_run_async(workspace_id, project_path, base_branch, status))
    except Exception as exc:  # noqa: BLE001 - top-level guard for the daemon thread
        log.exception("review pipeline crashed for workspace %s", workspace_id)
        status.error = str(exc)
    finally:
        if status.state not in _TERMINAL_STATES:
            status.state = "failed"
            if not status.error:
                status.error = "pipeline thread exited without reaching a terminal state"
        if status.finished_at is None:
            status.finished_at = time.time()


async def _run_async(
    workspace_id: int,
    project_path: Path,
    base_branch: str,
    status: PipelineStatus,
) -> None:
    status.state = "filtering"
    try:
        reviewable = await asyncio.to_thread(
            diff_filter.list_reviewable_files, project_path, base_branch
        )
    except Exception as exc:  # noqa: BLE001 - diff-filter failure is recorded, not raised
        log.exception("diff filter failed for workspace %s", workspace_id)
        status.state = "failed"
        status.error = f"diff filter failed: {exc}"
        status.finished_at = time.time()
        return

    status.files = {rf.path: FileResult(file=rf.path) for rf in reviewable}
    status.integration = {name: "pending" for name in _INTEGRATION_AGENTS}

    await _run_file_stage(workspace_id, project_path, reviewable, status, base_branch)
    await _run_integration_stage(workspace_id, project_path, status)

    status.state = "done"
    status.finished_at = time.time()


async def _run_file_stage(
    workspace_id: int,
    project_path: Path,
    reviewable: list,
    status: PipelineStatus,
    base_ref: str,
) -> None:
    status.state = "file_stage"
    if not reviewable:
        return

    semaphore = asyncio.Semaphore(_concurrency())

    async def _bounded(rf) -> None:
        async with semaphore:
            await _review_one_file(workspace_id, project_path, rf.path, status, base_ref)

    await asyncio.gather(*(_bounded(rf) for rf in reviewable))


async def _run_integration_stage(
    workspace_id: int,
    project_path: Path,
    status: PipelineStatus,
) -> None:
    status.state = "integration_stage"
    for agent_name in _INTEGRATION_AGENTS:
        status.integration[agent_name] = "running"

    async def _run_one(agent_name: str) -> None:
        try:
            await _run_integration_agent(workspace_id, project_path, agent_name)
            status.integration[agent_name] = "done"
        except Exception as exc:  # noqa: BLE001 - each agent isolated
            log.exception("integration agent %s failed", agent_name)
            status.integration[agent_name] = "failed"
            status.integration_errors[agent_name] = str(exc)

    await asyncio.gather(
        *(_run_one(name) for name in _INTEGRATION_AGENTS),
        return_exceptions=False,
    )


async def _review_one_file(
    workspace_id: int,
    project_path: Path,
    file_path: str,
    status: PipelineStatus,
    base_ref: str,
) -> None:
    result = status.files[file_path]
    result.status = "running"
    try:
        findings = await _spawn_file_reviewer(project_path, file_path, base_ref)
    except Exception as exc:  # noqa: BLE001 - failures captured on FileResult, never propagate
        log.exception("file reviewer failed for %s", file_path)
        result.status = "failed"
        result.error = str(exc)
        return

    result.findings_count = len(findings)
    for finding in findings:
        try:
            _submit_finding(workspace_id, file_path, finding)
        except Exception as submit_exc:  # noqa: BLE001 - per-finding DB errors are isolated
            log.exception(
                "failed to submit finding for ws=%s file=%s", workspace_id, file_path
            )
            result.submit_failures += 1
    result.status = "done"


def _get_file_diff(project_path: Path, file_path: str, base_ref: str) -> str:
    """Get the diff for a single file vs base. Empty string on any failure."""
    try:
        result = subprocess.run(
            ["git", "diff", f"{base_ref}..HEAD", "--", file_path],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:  # noqa: BLE001 - best-effort; missing diff degrades gracefully
        return ""


async def _spawn_file_reviewer(
    project_path: Path, file_path: str, base_ref: str = "main"
) -> list[dict]:
    hunk = _get_file_diff(project_path, file_path, base_ref)
    prompt = (
        f"Review this file's changes for LOCAL issues only.\n\n"
        f"File: {file_path}\n\n"
        f"Diff (against {base_ref}):\n```\n{hunk}\n```\n\n"
        f"Output JSON per your role spec."
    )
    stdout = await _spawn_claude_agent(
        agent=_FILE_REVIEWER_AGENT,
        prompt=prompt,
        project_path=project_path,
        # The file-reviewer agent uses one turn for the Read tool call and a
        # second turn for the final JSON message. ``--max-turns 1`` exits with
        # ``error_max_turns`` before the agent can emit its envelope. Three
        # turns gives a small buffer for a follow-up Read on long files.
        max_turns=3,
        timeout_s=_timeout_s(),
        suppress_mcp=True,
    )
    return _parse_file_reviewer_findings(stdout)


async def _run_integration_agent(
    workspace_id: int,
    project_path: Path,
    agent_name: str,
) -> None:
    prompt = "Review the current branch diff for cross-file issues."
    stdout = await _spawn_claude_agent(
        agent=agent_name,
        prompt=prompt,
        project_path=project_path,
        max_turns=5,
        timeout_s=_timeout_s() * _INTEGRATION_TIMEOUT_MULTIPLIER,
    )
    try:
        envelope = json.loads(stdout) if stdout.strip() else {}
        if envelope.get("is_error"):
            log.warning(
                "%s returned is_error=True; findings may be missing",
                agent_name,
            )
    except json.JSONDecodeError:
        log.warning(
            "%s envelope malformed but findings may have been submitted via MCP; "
            "check workspace_get_review_issues",
            agent_name,
        )


async def _spawn_claude_agent(
    agent: str,
    prompt: str,
    project_path: Path,
    max_turns: int,
    timeout_s: int,
    suppress_mcp: bool = False,
) -> str:
    """Spawn ``claude -p --agent <agent>`` and return stdout.

    When ``suppress_mcp`` is True, ``--strict-mcp-config`` is passed and no
    ``--mcp-config`` files are supplied — this disables every MCP server for
    that invocation. Used for the file-reviewer fan-out so each haiku-class
    subprocess does not load the workspace's full opus-class MCP tool schema
    (~20k cache-creation tokens per call). The integration reviewers must
    keep MCP enabled because they self-submit findings via
    ``workspace_submit_review_issue``.
    """
    argv = ["claude", "-p", "--agent", agent]
    if suppress_mcp:
        argv.append("--strict-mcp-config")
    argv.extend([
        "--output-format", "json",
        "--max-turns", str(max_turns),
    ])
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(project_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")), timeout=timeout_s
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        try:
            await proc.wait()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
        raise RuntimeError(f"{agent} timeout after {timeout_s}s") from exc

    if proc.returncode != 0:
        stderr_excerpt = stderr_bytes.decode(errors="replace")[:_STDERR_EXCERPT_CHARS]
        raise RuntimeError(
            f"{agent} exit {proc.returncode}: {stderr_excerpt}"
        )
    return stdout_bytes.decode(errors="replace")


def _parse_file_reviewer_findings(stdout: str) -> list[dict]:
    result_str = _extract_envelope_result(stdout)
    if not result_str.strip():
        log.warning("file-reviewer returned empty result — treating as no findings")
        return []
    cleaned = _strip_markdown_fences(result_str.strip())
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"file-reviewer returned invalid JSON: {exc}") from exc
    findings = payload.get("findings", [])
    if not isinstance(findings, list):
        raise RuntimeError("file-reviewer payload missing 'findings' list")
    return [f for f in findings if isinstance(f, dict)]


def _strip_markdown_fences(text: str) -> str:
    """Remove a single set of opening/closing ``` fences if present.

    The file-reviewer agent is instructed to emit raw JSON, but haiku-class
    models occasionally wrap output in ```json ... ``` blocks. Tolerate that
    rather than failing the file.
    """
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def _extract_envelope_result(stdout: str) -> str:
    """Pull the agent's stdout out of the ``claude -p --output-format json`` envelope.

    The envelope shape is ``{"result": "<agent text or JSON string>", ...}``.
    """
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"agent envelope is not valid JSON: {exc}") from exc
    if not isinstance(envelope, dict):
        raise RuntimeError("agent envelope is not a JSON object")
    result = envelope.get("result", "")
    return result if isinstance(result, str) else json.dumps(result)


def _coerce_line(value) -> int:
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
            if parsed >= 1:
                return parsed
        except ValueError:
            pass
    return 1


def _submit_finding(workspace_id: int, file_path: str, finding: dict) -> None:
    line = _coerce_line(finding.get("line"))
    summary = str(finding.get("summary") or "").strip()
    if not summary:
        return
    severity = finding.get("severity", "major")
    issue_type = finding.get("type", "unspecified")
    description = f"[{severity}/{issue_type}] {summary}"

    db = get_db()
    try:
        submit_review_issue(
            db,
            workspace_id=workspace_id,
            file_path=file_path,
            line_start=line,
            line_end=line,
            description=description,
            author=_FILE_REVIEWER_AGENT,
        )
        db.commit()
    finally:
        db.close()
