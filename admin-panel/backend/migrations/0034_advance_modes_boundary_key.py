"""Reshape advance-mode storage to boundary_key (TEXT) instead of major_phase (INTEGER).

Replaces the 5-slot major-phase table with a generic (project_id, boundary_key)
mapping. Sub-phase boundaries within Implementation (3.N) can now be configured
independently. The template key '3.x' captures the default for 3.N values not
explicitly set.
"""
from yoyo import step


step("""
    CREATE TABLE project_boundary_modes (
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        boundary_key TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'none' CHECK (mode IN ('none', 'compact', 'clear')),
        PRIMARY KEY (project_id, boundary_key)
    )
""")

step("""
    INSERT INTO project_boundary_modes (project_id, boundary_key, mode)
    SELECT project_id, CAST(major_phase AS TEXT), mode
    FROM project_advance_modes
""")

step("""
    INSERT OR IGNORE INTO project_boundary_modes (project_id, boundary_key, mode)
    SELECT id, '1', 'none' FROM projects
""")
step("""
    INSERT OR IGNORE INTO project_boundary_modes (project_id, boundary_key, mode)
    SELECT id, '2', 'compact' FROM projects
""")
step("""
    INSERT OR IGNORE INTO project_boundary_modes (project_id, boundary_key, mode)
    SELECT id, '3.1', 'clear' FROM projects
""")
step("""
    INSERT OR IGNORE INTO project_boundary_modes (project_id, boundary_key, mode)
    SELECT id, '3.x', 'compact' FROM projects
""")
step("""
    INSERT OR IGNORE INTO project_boundary_modes (project_id, boundary_key, mode)
    SELECT id, '4', 'clear' FROM projects
""")
step("""
    INSERT OR IGNORE INTO project_boundary_modes (project_id, boundary_key, mode)
    SELECT id, '5', 'none' FROM projects
""")

step(
    "DROP TABLE project_advance_modes",
    """
    CREATE TABLE project_advance_modes (
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        major_phase INTEGER NOT NULL CHECK (major_phase BETWEEN 1 AND 5),
        mode TEXT NOT NULL DEFAULT 'none' CHECK (mode IN ('none', 'compact', 'clear')),
        PRIMARY KEY (project_id, major_phase)
    )
    """,
)
