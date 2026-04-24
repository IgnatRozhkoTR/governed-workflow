"""Tests for core.db — connection handling and file permissions."""
import stat
import sys

import pytest


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file modes only")
def test_init_db_restricts_sqlite_file_to_owner_only(setup_db):
    """After init_db() runs, the DB file must be mode 0600 on POSIX."""
    db_path = setup_db

    mode = stat.S_IMODE(db_path.stat().st_mode)
    assert mode == 0o600, f"DB file mode is {oct(mode)} — expected 0o600"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file modes only")
def test_init_db_restricts_wal_sidecar_to_owner_only(setup_db):
    """WAL sidecar, when present, must also be mode 0600 on POSIX."""
    wal_path = setup_db.with_name(setup_db.name + "-wal")

    if not wal_path.exists():
        pytest.skip("WAL sidecar not created on this platform run")

    mode = stat.S_IMODE(wal_path.stat().st_mode)
    assert mode == 0o600, f"WAL file mode is {oct(mode)} — expected 0o600"
