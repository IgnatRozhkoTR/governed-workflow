"""Work modes: named, reusable phase enable/disable presets per workspace.

Introduces the schema that lets a workspace point at a named ``work_mode``
preset, plus a single seeded system mode named ``basic`` whose enabled set is
the canonical phase sequence (everything in ``PHASE_REGISTRY`` except the
templated ``3.x.K`` placeholders, which are expanded per-plan at runtime).

The basic mode replaces the hardcoded ``ALWAYS_ON_PHASE_IDS`` /
``COMMIT_GATE_PATTERN`` enforcement that previously lived in ``phase_settings``.
After this migration, mandatory-phase pinning is data-driven and lives in
``work_mode_phases`` rows, not in service-layer constants.

Building additional work modes beyond ``basic`` is out of scope for sub-phase
3.6: this migration deliberately seeds exactly one preset.
"""
from yoyo import step


def seed_basic_mode(conn):
    """Seed the system mode ``basic`` with every canonical phase enabled.

    Idempotent: a re-run on a database that already contains the row is a
    no-op. Phase ids are pulled from ``PHASE_REGISTRY`` so any newly
    registered static phases land in ``basic`` automatically. Templated ids
    (``3.x.K``) are excluded — they describe a per-plan family, not a
    standalone enable/disable target.
    """
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated, phase_key

    cursor = conn.cursor()
    cursor.execute("SELECT id FROM work_modes WHERE name = 'basic'")
    existing = cursor.fetchone()
    if existing is not None:
        return

    cursor.execute(
        "INSERT INTO work_modes (name, description, origin) "
        "VALUES (?, ?, 'system')",
        ("basic", "Default workflow with all phases enabled"),
    )
    mode_id = cursor.lastrowid

    canonical_ids = sorted(
        (pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)),
        key=phase_key,
    )
    for position, phase_id in enumerate(canonical_ids):
        cursor.execute(
            "INSERT INTO work_mode_phases (work_mode_id, phase_id, enabled, position) "
            "VALUES (?, ?, 1, ?)",
            (mode_id, phase_id, position),
        )


def add_workspace_work_mode_id(conn):
    """Add ``workspaces.work_mode_id`` column when missing.

    Sentinel-based ALTER so an interrupted prior run doesn't break re-apply.
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}
    if "work_mode_id" in existing:
        return
    cursor.execute(
        "ALTER TABLE workspaces ADD COLUMN work_mode_id INTEGER "
        "REFERENCES work_modes(id) ON DELETE SET NULL"
    )


step("""
    CREATE TABLE IF NOT EXISTS work_modes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        origin TEXT NOT NULL DEFAULT 'user' CHECK (origin IN ('system','user')),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
""")

step("""
    CREATE TABLE IF NOT EXISTS work_mode_phases (
        work_mode_id INTEGER NOT NULL REFERENCES work_modes(id) ON DELETE CASCADE,
        phase_id TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        position INTEGER NOT NULL,
        PRIMARY KEY (work_mode_id, phase_id)
    )
""")

step(add_workspace_work_mode_id)
step(seed_basic_mode)
