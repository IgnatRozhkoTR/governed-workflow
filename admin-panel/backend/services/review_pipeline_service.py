"""Headless review pipeline for phase 4.0 blind review.

Triggered as a background thread by ``transition_phase`` when a workspace
enters phase ``4.0``. The pipeline:

1. Resolves the reviewable file list via :mod:`services.diff_filter`.
2. Fans out one ``claude -p --agent file-reviewer`` subprocess per file,
   capped by ``GOVERNED_WORKFLOW_REVIEW_CONCURRENCY`` (default 8). Each
   per-file agent returns JSON ``{file, findings: [...]}`` on stdout; the
   findings are written to the discussions table via
   :func:`services.comment_service.submit_review_issue`.
3. Runs the integration reviewers ``code-reviewer`` and
   ``senior-code-validator`` sequentially. ``code-reviewer`` self-submits
   findings through MCP, so the pipeline only awaits its exit code.
   ``senior-code-validator`` returns prose; its full text is attached as a
   single review issue against the synthetic ``(integration)`` path.

Agent failures (timeout, non-zero exit, JSON parse failure) are recorded as
``review-agent-failure`` typed issues so the user can see them in the admin
panel — the pipeline never raises out to the caller.

Status is exposed via :func:`get_status` (in-memory, keyed by
``workspace_id``) and the ``/api/workspaces/<id>/review-pipeline-status``
HTTP endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
_INTEGRATION_AGENTS: tuple[str, ...] = ("code-reviewer", "senior-code-validator")
_SELF_SUBMITTING_AGENTS: frozenset[str] = frozenset({"code-reviewer"})

_STDERR_EXCERPT_CHARS = 500
_TEXT_FINDING_TRUNCATE_CHARS = 2000

_INTEGRATION_FILE_PATH = "(integration)"
_PIPELINE_FILE_PATH = "(pipeline)"

_FAILURE_PREFIX = "[review-agent-failure]"

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
    error: str | None = None


@dataclass
class PipelineStatus:
    workspace_id: int
    state: PipelineState = "queued"
    files: dict[str, FileResult] = field(default_factory=dict)
    integration: dict[str, AgentState] = field(default_factory=dict)
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


def _set_status(status: PipelineStatus) -> None:
    with _STATUS_LOCK:
        _STATUS[status.workspace_id] = status


def start_in_background(
    workspace_id: int,
    project_path: Path,
    base_branch: str = "main",
) -> threading.Thread:
    """Start the pipeline in a daemon thread and return it.

    Flask is synchronous; ``asyncio.create_task`` cannot be used from a
    request handler. The thread owns its own DB connection (Sqlite handles
    are not thread-safe across threads) and its own asyncio event loop.
    """
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
        status.state = "failed"
        status.error = str(exc)
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

    await _run_file_stage(workspace_id, project_path, reviewable, status)
    await _run_integration_stage(workspace_id, project_path, status)

    status.state = "done"
    status.finished_at = time.time()


async def _run_file_stage(
    workspace_id: int,
    project_path: Path,
    reviewable: list,
    status: PipelineStatus,
) -> None:
    status.state = "file_stage"
    if not reviewable:
        return

    semaphore = asyncio.Semaphore(_concurrency())

    async def _bounded(rf) -> None:
        async with semaphore:
            await _review_one_file(workspace_id, project_path, rf.path, status)

    await asyncio.gather(*(_bounded(rf) for rf in reviewable))


async def _run_integration_stage(
    workspace_id: int,
    project_path: Path,
    status: PipelineStatus,
) -> None:
    status.state = "integration_stage"
    for agent_name in _INTEGRATION_AGENTS:
        status.integration[agent_name] = "running"
        try:
            await _run_integration_agent(workspace_id, project_path, agent_name)
            status.integration[agent_name] = "done"
        except Exception as exc:  # noqa: BLE001 - each agent isolated
            log.exception("integration agent %s failed", agent_name)
            status.integration[agent_name] = "failed"
            _record_agent_failure(workspace_id, agent_name, str(exc))


async def _review_one_file(
    workspace_id: int,
    project_path: Path,
    file_path: str,
    status: PipelineStatus,
) -> None:
    result = status.files[file_path]
    result.status = "running"
    try:
        findings = await _spawn_file_reviewer(project_path, file_path)
    except Exception as exc:  # noqa: BLE001 - failures recorded as issues, never propagate
        log.exception("file reviewer failed for %s", file_path)
        result.status = "failed"
        result.error = str(exc)
        _record_agent_failure(
            workspace_id, _FILE_REVIEWER_AGENT, str(exc), file_path=file_path
        )
        return

    for finding in findings:
        _submit_finding(workspace_id, file_path, finding)
    result.findings_count = len(findings)
    result.status = "done"


async def _spawn_file_reviewer(project_path: Path, file_path: str) -> list[dict]:
    prompt = (
        f"Review the file: {file_path}\n\n"
        "Report only LOCAL issues per your role spec."
    )
    stdout = await _spawn_claude_agent(
        agent=_FILE_REVIEWER_AGENT,
        prompt=prompt,
        project_path=project_path,
        max_turns=1,
        timeout_s=_timeout_s(),
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
    if agent_name in _SELF_SUBMITTING_AGENTS:
        return

    text = _extract_envelope_result(stdout)
    if text.strip():
        _submit_text_finding(workspace_id, agent_name, text)


async def _spawn_claude_agent(
    agent: str,
    prompt: str,
    project_path: Path,
    max_turns: int,
    timeout_s: int,
) -> str:
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p",
        "--agent",
        agent,
        "--output-format",
        "json",
        "--max-turns",
        str(max_turns),
        prompt,
        cwd=str(project_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_s
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
        return []
    try:
        payload = json.loads(result_str)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"file-reviewer returned invalid JSON: {exc}") from exc
    findings = payload.get("findings", [])
    if not isinstance(findings, list):
        raise RuntimeError("file-reviewer payload missing 'findings' list")
    return [f for f in findings if isinstance(f, dict)]


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


def _submit_text_finding(workspace_id: int, source: str, text: str) -> None:
    truncated = text.strip()[:_TEXT_FINDING_TRUNCATE_CHARS]
    description = f"[integration:{source}] {truncated}"

    db = get_db()
    try:
        submit_review_issue(
            db,
            workspace_id=workspace_id,
            file_path=_INTEGRATION_FILE_PATH,
            line_start=1,
            line_end=1,
            description=description,
            author=source,
        )
        db.commit()
    finally:
        db.close()


def _record_agent_failure(
    workspace_id: int,
    agent_name: str,
    error: str,
    file_path: str | None = None,
) -> None:
    target = file_path or _PIPELINE_FILE_PATH
    excerpt = error[:_STDERR_EXCERPT_CHARS]
    description = f"{_FAILURE_PREFIX} {agent_name}: {excerpt}"

    db = get_db()
    try:
        submit_review_issue(
            db,
            workspace_id=workspace_id,
            file_path=target,
            line_start=1,
            line_end=1,
            description=description,
            author=agent_name,
        )
        db.commit()
    except Exception:  # noqa: BLE001 - last-resort defensive
        log.exception(
            "failed to persist agent-failure issue for ws=%s agent=%s",
            workspace_id,
            agent_name,
        )
    finally:
        db.close()
