"""Shared fixtures for admin panel integration tests."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

from testing_utils import _git, GIT_ENV

# Add server/ to path for imports
SERVER_DIR = str(Path(__file__).resolve().parent.parent)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


@pytest.fixture(scope="session", autouse=True)
def disable_review_pipeline_subprocesses():
    """Prevent transition_phase from forking real claude subprocesses in tests.

    Tests that exercise the pipeline itself patch its async helpers directly,
    so this flag is fine to keep on across the suite.
    """
    import os
    previous = os.environ.get("GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE")
    os.environ["GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE"] = "1"
    yield
    if previous is None:
        os.environ.pop("GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE", None)
    else:
        os.environ["GOVERNED_WORKFLOW_DISABLE_REVIEW_PIPELINE"] = previous


@pytest.fixture(scope="session", autouse=True)
def setup_db(tmp_path_factory):
    """Patch DB_PATH to temp file before any app imports."""
    db_dir = tmp_path_factory.mktemp("db")
    db_file = db_dir / "admin-panel.db"

    from core import db as db_module
    db_module.DB_PATH = db_file
    db_module.init_db()
    db = db_module.get_db()
    db.execute("PRAGMA journal_mode=WAL")
    db.close()

    yield db_file


@pytest.fixture(scope="session")
def admin_token(setup_db):
    """Mint a real admin token for the session and persist its hash.

    Protected routes require a valid token, so the wrapped ``client`` fixture
    injects this value on every request. ``clean_db`` re-inserts the hash after
    truncating ``device_settings`` so the wrapper keeps working across tests.
    """
    from core.db import get_db
    from core.device_settings import generate_token, set_admin_token
    token = generate_token()
    db = get_db()
    try:
        set_admin_token(db, token)
        db.commit()
    finally:
        db.close()
    return token


@pytest.fixture(autouse=True)
def clean_db(setup_db, admin_token):
    """Truncate all tables between tests for isolation."""
    yield  # let the test run first
    # Clean up AFTER the test
    from core.db import get_db
    from core.device_settings import set_admin_token
    import sqlite3
    tables = [
        "acceptance_criteria", "review_issues", "discussions",
        "research_entries", "progress_entries", "session_history",
        "phase_history", "proposals", "workspaces", "projects",
        "modules_enabled",
        "verification_step_results", "verification_runs",
        "project_verification_profiles",
        "device_settings",
        "phase_settings",
        "project_boundary_modes",
    ]

    def _do_clean(db):
        db.execute("PRAGMA busy_timeout = 5000")
        for table in tables:
            db.execute(f"DELETE FROM {table}")
        # Remove only user-created profiles so seeded system profiles persist
        db.execute("DELETE FROM verification_steps WHERE profile_id IN "
                   "(SELECT id FROM verification_profiles WHERE origin = 'user')")
        db.execute("DELETE FROM verification_profiles WHERE origin = 'user'")
        # Restore the session admin token so the next test's wrapped client still works.
        set_admin_token(db, admin_token)
        db.commit()
        db.close()

    try:
        _do_clean(get_db())
    except sqlite3.OperationalError:
        # If DB is locked, force close all connections and retry
        import gc
        gc.collect()
        _do_clean(get_db())


@pytest.fixture(scope="session")
def app(setup_db):
    """Create Flask test app."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


class AuthedClient:
    """Flask test client wrapper that injects the admin bearer token.

    Forwards every HTTP verb (``get``, ``post``, ``put``, ``delete``, ``patch``,
    ``head``, ``options``) to the underlying ``test_client``, auto-populating
    ``Authorization: Bearer <token>`` when the caller did not already set one.
    Any other attribute access (e.g. ``session_transaction``) falls through to
    the wrapped client so tests can still reach native test-client APIs.
    """

    _VERBS = ("get", "post", "put", "delete", "patch", "head", "options")

    def __init__(self, client, token):
        self._client = client
        self._token = token

    def _with_auth(self, kwargs):
        headers = kwargs.get("headers")
        if headers is None:
            kwargs["headers"] = {"Authorization": f"Bearer {self._token}"}
            return kwargs
        # Support both dict-like and Werkzeug Headers objects.
        has_auth = False
        try:
            has_auth = "Authorization" in headers
        except TypeError:
            has_auth = any(
                (isinstance(item, tuple) and len(item) >= 1 and item[0] == "Authorization")
                for item in headers
            )
        if has_auth:
            return kwargs
        if isinstance(headers, dict):
            new_headers = dict(headers)
            new_headers["Authorization"] = f"Bearer {self._token}"
            kwargs["headers"] = new_headers
        else:
            # Copy into a dict so we don't mutate the caller's object.
            new_headers = {}
            for item in headers:
                if isinstance(item, tuple) and len(item) >= 2:
                    new_headers[item[0]] = item[1]
            new_headers["Authorization"] = f"Bearer {self._token}"
            kwargs["headers"] = new_headers
        return kwargs

    def _verb(self, name, *args, **kwargs):
        kwargs = self._with_auth(kwargs)
        return getattr(self._client, name)(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self._verb("get", *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._verb("post", *args, **kwargs)

    def put(self, *args, **kwargs):
        return self._verb("put", *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._verb("delete", *args, **kwargs)

    def patch(self, *args, **kwargs):
        return self._verb("patch", *args, **kwargs)

    def head(self, *args, **kwargs):
        return self._verb("head", *args, **kwargs)

    def options(self, *args, **kwargs):
        return self._verb("options", *args, **kwargs)

    def __getattr__(self, item):
        return getattr(self._client, item)


@pytest.fixture(scope="session")
def client(app, admin_token):
    """Flask test client with auto-injected admin token."""
    return AuthedClient(app.test_client(), admin_token)


@pytest.fixture(scope="session")
def raw_client(app):
    """Unwrapped Flask test client for tests exercising the real middleware."""
    return app.test_client()


@pytest.fixture
def git_repo(tmp_path):
    """Create a temp git repo with develop branch and initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "checkout", "-b", "develop")
    (repo / ".gitignore").write_text("")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Initial commit")
    return str(repo)


@pytest.fixture
def git_repo_with_files(git_repo):
    """Git repo with committed source and test files."""
    repo = Path(git_repo)
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text(
        "def main():\n    print('hello')\n\ndef helper():\n    return True\n"
    )
    (repo / "src" / "utils.py").write_text(
        "def format_name(name):\n    return name.strip().title()\n"
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_main.py").write_text(
        "def test_main():\n    assert True\n\ndef test_helper():\n    assert True\n"
    )
    (repo / "features").mkdir()
    (repo / "features" / "login.feature").write_text(
        "Feature: Login\n\n  Scenario: Valid login\n    Given a user\n\n  Scenario: Invalid login\n    Given no user\n"
    )
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "Add source files")
    return git_repo


@pytest.fixture
def project(clean_db, git_repo):
    """Register a test project directly in DB."""
    from core.db import get_db
    db = get_db()
    project_id = "test-project"
    registered = datetime.now().isoformat()
    db.execute(
        "INSERT INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", git_repo, registered)
    )
    db.commit()
    db.close()
    return {"id": project_id, "name": "Test Project", "path": git_repo, "registered": registered}


@pytest.fixture
def workspace(project, git_repo):
    """Create a workspace at phase 0."""
    from core.db import get_db
    db = get_db()
    now = datetime.now().isoformat()
    cursor = db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, ?, 'active', '0', ?, ?)",
        (project["id"], "feature/test", "feature-test", git_repo,
         now, '{"description":"","systemDiagram":"","execution":[]}', "develop")
    )
    ws_id = cursor.lastrowid
    db.commit()
    db.close()
    return {
        "id": ws_id,
        "project_id": project["id"],
        "branch": "feature/test",
        "sanitized_branch": "feature-test",
        "working_dir": git_repo,
        "phase": "0",
    }


@pytest.fixture
def second_workspace(project, git_repo):
    """Create a second workspace in the same project, simulating a different branch."""
    from core.db import get_db
    db = get_db()
    now = datetime.now().isoformat()
    cursor = db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, ?, 'active', '0', ?, ?)",
        (project["id"], "feature/other", "feature-other", git_repo,
         now, '{"description":"","systemDiagram":"","execution":[]}', "develop")
    )
    ws_id = cursor.lastrowid
    db.commit()
    db.close()
    return {
        "id": ws_id,
        "project_id": project["id"],
        "branch": "feature/other",
        "sanitized_branch": "feature-other",
        "working_dir": git_repo,
        "phase": "0",
    }
