"""Database connection and migration management."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "admin-panel.db"


def ws_field(ws, field, default=None):
    """Get a workspace field with a default for columns added via migration."""
    return ws[field] if field in ws.keys() else default


def get_db():
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA busy_timeout = 5000")
    return db


@contextmanager
def get_db_ctx():
    """Context manager for DB connections: ``with get_db_ctx() as db:``."""
    db = get_db()
    try:
        yield db
    finally:
        db.close()


def _restrict_db_file_mode():
    """Best-effort: set 0600 on the SQLite DB and its WAL/SHM sidecars.

    Same-UID processes (including agents running in the user's shell) can still
    read the DB — OS permissions do not defend against that. This just denies
    OTHER local users on the machine, and is a cheap defensive default.
    """
    for path in (DB_PATH, DB_PATH.with_name(DB_PATH.name + "-wal"),
                 DB_PATH.with_name(DB_PATH.name + "-shm")):
        if path.exists():
            try:
                path.chmod(0o600)
            except (OSError, NotImplementedError):
                pass


def init_db():
    """Apply any pending database migrations."""
    from yoyo import read_migrations, get_backend

    backend = get_backend(f"sqlite:///{DB_PATH}")
    migrations = read_migrations(
        str(Path(__file__).resolve().parent.parent / "migrations")
    )

    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))

    _restrict_db_file_mode()
