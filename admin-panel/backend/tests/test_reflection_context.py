"""Tests for services.reflection_context.gather_reflection_context."""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from core.db import get_db
from services.comment_service import submit_review_issue
from services.reflection_context import gather_reflection_context


# ── Git helpers ───────────────────────────────────────────────────────────────

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


def _g(repo, *args):
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        env={**os.environ, **_GIT_ENV},
    )


def _make_git_repo(tmp_path):
    """Create a two-branch repo: base has a.py; feature adds b.py."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _g(repo, "init")
    _g(repo, "config", "user.name", "Test")
    _g(repo, "config", "user.email", "test@test.com")
    _g(repo, "checkout", "-b", "main")
    (repo / "a.py").write_text("a = 1\n")
    _g(repo, "add", ".")
    _g(repo, "commit", "-m", "base commit")

    _g(repo, "checkout", "-b", "feature")
    (repo / "b.py").write_text("b = 2\n")
    _g(repo, "add", ".")
    _g(repo, "commit", "-m", "feature commit")
    return repo


# ── JSONL transcript helpers ──────────────────────────────────────────────────

def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line))
            fh.write("\n")


def _user_entry(text: str) -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": text},
    }


def _assistant_entry(text: str) -> dict:
    return {
        "type": "assistant",
        "isSidechain": False,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _transcript_path(claude_home: Path, project_path: Path, session_id: str) -> Path:
    from services.session_transcript import encode_project_path
    encoded = encode_project_path(project_path)
    return claude_home / "projects" / encoded / f"{session_id}.jsonl"


# ── DB fixture helpers ────────────────────────────────────────────────────────

def _insert_project(db, project_id, repo_path):
    db.execute(
        "INSERT INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        (project_id, "Test", str(repo_path), datetime.now().isoformat()),
    )


def _plan_with_scope(scope_map):
    """Build a plan_json string whose execution items embed the given scope map."""
    execution = [
        {"id": item_id, "name": item_id, "scope": scope, "tasks": []}
        for item_id, scope in (scope_map or {}).items()
    ]
    return json.dumps({"description": "", "systemDiagram": "", "execution": execution})


def _insert_workspace(db, project_id, repo_path, *, scope_map=None, session_id=None, source_branch="main"):
    cursor = db.execute(
        "INSERT INTO workspaces "
        "(project_id, branch, sanitized_branch, working_dir, created, status, phase, "
        "plan_json, source_branch, session_id) "
        "VALUES (?, ?, ?, ?, ?, 'active', '0', ?, ?, ?)",
        (
            project_id,
            "feature/x",
            "feature-x",
            str(repo_path),
            datetime.now().isoformat(),
            _plan_with_scope(scope_map),
            source_branch,
            session_id,
        ),
    )
    return cursor.lastrowid


def _fetch_ws(db, ws_id):
    return db.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_gather_reflection_context_returns_all_four_blobs_when_everything_present(tmp_path, clean_db):
    repo = _make_git_repo(tmp_path)
    claude_home = tmp_path / "claude_home"
    session_id = "sess-all"

    jsonl = _transcript_path(claude_home, repo, session_id)
    _write_jsonl(jsonl, [
        _user_entry("what should I do?"),
        _assistant_entry("implement b.py"),
    ])

    scope_map = {"3.1": {"must": ["b.py"], "may": []}}

    db = get_db()
    try:
        _insert_project(db, "p1", repo)
        ws_id = _insert_workspace(
            db, "p1", repo,
            scope_map=scope_map,
            session_id=session_id,
            source_branch="main",
        )
        submit_review_issue(db, ws_id, "b.py", 1, 3, "missing docstring")
        db.commit()

        ws = _fetch_ws(db, ws_id)
        ctx = gather_reflection_context(
            db, ws,
            project_path=repo,
            max_transcript_messages=400,
            claude_home=claude_home,
        )
    finally:
        db.close()

    assert ctx.workspace_id == ws_id
    assert ctx.branch == "feature/x"
    assert ctx.base_branch == "main"
    assert ctx.scope == {"3.1": {"must": ["b.py"], "may": []}}
    assert "b.py" in ctx.branch_diff
    assert len(ctx.review_findings) == 1
    assert ctx.review_findings[0]["file_path"] == "b.py"
    assert len(ctx.transcript) == 2
    assert ctx.transcript[0]["role"] == "user"
    assert ctx.transcript[1]["role"] == "assistant"
    assert ctx.transcript_truncated is False


def test_gather_reflection_context_returns_empty_transcript_when_session_id_missing(tmp_path, clean_db):
    repo = _make_git_repo(tmp_path)

    db = get_db()
    try:
        _insert_project(db, "p2", repo)
        ws_id = _insert_workspace(db, "p2", repo, session_id=None)
        db.commit()

        ws = _fetch_ws(db, ws_id)
        ctx = gather_reflection_context(db, ws, project_path=repo)
    finally:
        db.close()

    assert ctx.transcript == []
    assert ctx.transcript_truncated is False


def test_gather_reflection_context_returns_empty_transcript_when_jsonl_missing(tmp_path, clean_db):
    repo = _make_git_repo(tmp_path)

    db = get_db()
    try:
        _insert_project(db, "p3", repo)
        ws_id = _insert_workspace(db, "p3", repo, session_id="no-such-session")
        db.commit()

        ws = _fetch_ws(db, ws_id)
        ctx = gather_reflection_context(db, ws, project_path=repo)
    finally:
        db.close()

    assert ctx.transcript == []
    assert ctx.transcript_truncated is False


def test_gather_reflection_context_returns_empty_review_findings_when_none_exist(tmp_path, clean_db):
    repo = _make_git_repo(tmp_path)

    db = get_db()
    try:
        _insert_project(db, "p4", repo)
        ws_id = _insert_workspace(db, "p4", repo)
        db.commit()

        ws = _fetch_ws(db, ws_id)
        ctx = gather_reflection_context(db, ws, project_path=repo)
    finally:
        db.close()

    assert ctx.review_findings == []


def test_gather_reflection_context_returns_empty_scope_when_unset(tmp_path, clean_db):
    repo = _make_git_repo(tmp_path)

    db = get_db()
    try:
        _insert_project(db, "p5", repo)
        ws_id = _insert_workspace(db, "p5", repo, scope_map=None)
        db.commit()

        ws = _fetch_ws(db, ws_id)
        ctx = gather_reflection_context(db, ws, project_path=repo)
    finally:
        db.close()

    assert ctx.scope == {}


def test_gather_reflection_context_marks_transcript_truncated_when_cap_hit(tmp_path, clean_db):
    repo = _make_git_repo(tmp_path)
    claude_home = tmp_path / "claude_home"
    session_id = "sess-trunc"

    entries = [_user_entry(f"msg {i}") for i in range(5)]
    jsonl = _transcript_path(claude_home, repo, session_id)
    _write_jsonl(jsonl, entries)

    db = get_db()
    try:
        _insert_project(db, "p6", repo)
        ws_id = _insert_workspace(db, "p6", repo, session_id=session_id)
        db.commit()

        ws = _fetch_ws(db, ws_id)
        ctx = gather_reflection_context(
            db, ws,
            project_path=repo,
            max_transcript_messages=5,
            claude_home=claude_home,
        )
    finally:
        db.close()

    assert len(ctx.transcript) == 5
    assert ctx.transcript_truncated is True
