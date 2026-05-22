"""Per-project advance-mode storage (sub-phase 3.2).

Stores the phase-advancement mode for each major phase (1–5) within a project.
Absence of a row means 'none' — the default — so no backfill is required.

Modes:
    none    — no automatic action on major-phase boundary (default)
    compact — compact the session when a major boundary is crossed
    clear   — clear the session when a major boundary is crossed
"""
from yoyo import step


step("""
    CREATE TABLE IF NOT EXISTS project_advance_modes (
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        major_phase INTEGER NOT NULL CHECK (major_phase BETWEEN 1 AND 5),
        mode TEXT NOT NULL DEFAULT 'none' CHECK (mode IN ('none', 'compact', 'clear')),
        PRIMARY KEY (project_id, major_phase)
    )
""")
