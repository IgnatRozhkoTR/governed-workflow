"""Promote proven research findings to memory_write proposals.

Scans proven research entries for the workspace, classifies each finding as
project-level or ticket-specific, gates project-level candidates through an LLM
check and a semantic dedup step, then emits memory_write proposals for survivors.
"""
import json
import re

from core import llm_client
from core.llm_client import LLMClientError
from services import memory_service
from services import proposal_service
from services.memory_provider import MemoryProviderError


_ARCHITECTURE_PATTERN = re.compile(
    r'\b(architecture|architectural|convention|pattern|across the codebase|throughout the project)\b',
    re.IGNORECASE,
)

_DEDUP_RELEVANCE_THRESHOLD = 0.85

_LLM_PROMPT_TEMPLATE = """\
Is the following finding broadly applicable to future tickets in this codebase, beyond the current ticket? Answer YES or NO with one-sentence justification.
Finding: {title}

{body}"""


class MemoryPromotionError(Exception):
    """Domain error for memory promotion operations.

    Codes:
        not_found            — workspace not found.
        llm_unconfigured     — no LLM API key set.
        provider_unavailable — memory backend not reachable.
        transient            — temporary failure; caller may retry.
    """

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _resolve_workspace(db, workspace_id: int) -> dict:
    row = db.execute(
        "SELECT id, project_id FROM workspaces WHERE id = ?", (workspace_id,)
    ).fetchone()
    if row is None:
        raise MemoryPromotionError(
            f"Workspace {workspace_id} not found",
            code="not_found",
        )
    return {"id": row["id"], "project_id": row["project_id"]}


def _load_proven_findings(db, workspace_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT id, findings_json FROM research_entries "
        "WHERE workspace_id = ? AND proven = 1",
        (workspace_id,),
    ).fetchall()
    findings: list[dict] = []
    for row in rows:
        try:
            entry_findings = json.loads(row["findings_json"])
        except (TypeError, ValueError):
            entry_findings = []
        if not isinstance(entry_findings, list):
            continue
        for finding in entry_findings:
            if not isinstance(finding, dict):
                continue
            findings.append(finding)
    return findings


def _normalize_title(title: str) -> str:
    return title.lower().strip()


def _count_title_recurrences(db, project_id) -> dict[str, int]:
    """Count how many proven research entries each title appears in, project-wide."""
    rows = db.execute(
        "SELECT re.findings_json FROM research_entries re "
        "JOIN workspaces ws ON ws.id = re.workspace_id "
        "WHERE ws.project_id = ? AND re.proven = 1",
        (project_id,),
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        try:
            entry_findings = json.loads(row["findings_json"])
        except (TypeError, ValueError):
            entry_findings = []
        seen_in_entry: set[str] = set()
        if not isinstance(entry_findings, list):
            continue
        for finding in entry_findings:
            if not isinstance(finding, dict):
                continue
            norm = _normalize_title(finding.get("summary", ""))
            if norm and norm not in seen_in_entry:
                seen_in_entry.add(norm)
                counts[norm] = counts.get(norm, 0) + 1
    return counts


def _is_project_level(finding: dict, title_counts: dict[str, int]) -> bool:
    proof_files = (finding.get("proof") or {}).get("files", []) or []
    if len(proof_files) > 2:
        return True

    title = finding.get("summary", "")
    body = finding.get("details", "")
    if _ARCHITECTURE_PATTERN.search(title + " " + body):
        return True

    norm = _normalize_title(title)
    if norm and title_counts.get(norm, 0) >= 2:
        return True

    return False


def _classify_project_level(findings: list[dict], title_counts: dict[str, int]) -> list[dict]:
    return [f for f in findings if _is_project_level(f, title_counts)]


def _llm_approves_one(finding: dict) -> bool:
    title = finding.get("summary", "")
    body = finding.get("details", "")
    prompt = _LLM_PROMPT_TEMPLATE.format(title=title, body=body)
    try:
        response = llm_client.complete(prompt, json_mode=False)
    except LLMClientError as exc:
        if exc.code == "unconfigured":
            raise MemoryPromotionError(str(exc), code="llm_unconfigured") from exc
        raise MemoryPromotionError(str(exc), code="transient") from exc
    return response.strip().upper().startswith("YES")


def _llm_filter(findings: list[dict]) -> list[dict]:
    return [f for f in findings if _llm_approves_one(f)]


def _is_duplicate(db, finding: dict, project_id) -> bool:
    title = finding.get("summary", "")
    scope_filter = [{"kind": "project", "project_id": str(project_id)}]
    try:
        results = memory_service.retrieve(db, query=title, scope_filter=scope_filter, limit=3)
    except MemoryProviderError as exc:
        if exc.code == "provider_unavailable":
            raise MemoryPromotionError(str(exc), code="provider_unavailable") from exc
        raise MemoryPromotionError(str(exc), code="transient") from exc
    return any(r.get("score", r.get("relevance", 0)) > _DEDUP_RELEVANCE_THRESHOLD for r in results)


def _drop_duplicates(db, findings: list[dict], project_id) -> list[dict]:
    return [f for f in findings if not _is_duplicate(db, f, project_id)]


def _emit_memory_proposals(db, findings: list[dict], workspace: dict) -> list[int]:
    proposal_ids: list[int] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        title = finding.get("summary", "")
        body = finding.get("details", "")
        if not title.strip():
            continue
        proposal = proposal_service.create(
            db,
            type="memory_write",
            title=title,
            body=body,
            payload={"title": title, "body": body},
            origin="memory_promotion",
            workspace_id=workspace["id"],
            project_id=workspace["project_id"],
        )
        proposal_ids.append(proposal["id"])
    return proposal_ids


def _empty_result(workspace_id: int) -> dict:
    return {
        "workspace_id": workspace_id,
        "candidates_examined": 0,
        "proposals_created": 0,
        "proposal_ids": [],
    }


def _build_result(workspace_id: int, candidates_examined: int, proposal_ids: list[int]) -> dict:
    return {
        "workspace_id": workspace_id,
        "candidates_examined": candidates_examined,
        "proposals_created": len(proposal_ids),
        "proposal_ids": proposal_ids,
    }


def promote(db, workspace_id: int) -> dict:
    """Scan proven research entries and emit memory_write proposals for project-level findings.

    Returns
        {workspace_id, candidates_examined, proposals_created, proposal_ids}

    Raises
        MemoryPromotionError(code='not_found')            — workspace missing.
        MemoryPromotionError(code='llm_unconfigured')     — no LLM API key.
        MemoryPromotionError(code='provider_unavailable') — memory backend down.
        MemoryPromotionError(code='transient')            — temporary failure.
    """
    workspace = _resolve_workspace(db, workspace_id)
    proven_findings = _load_proven_findings(db, workspace_id)
    title_recurrence = _count_title_recurrences(db, workspace["project_id"])
    candidates = _classify_project_level(proven_findings, title_recurrence)
    if not candidates:
        return _empty_result(workspace_id)
    llm_approved = _llm_filter(candidates)
    deduped = _drop_duplicates(db, llm_approved, workspace["project_id"])
    proposal_ids = _emit_memory_proposals(db, deduped, workspace)
    return _build_result(workspace_id, candidates_examined=len(candidates), proposal_ids=proposal_ids)
