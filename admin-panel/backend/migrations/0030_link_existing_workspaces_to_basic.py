"""Backfill ``workspaces.work_mode_id`` to the seeded ``basic`` mode.

After 0029 every workspace inherits the canonical phase sequence by default.
Migration is idempotent: workspaces that already point at a non-null mode
keep their assignment.
"""
from yoyo import step

step(
    "UPDATE workspaces "
    "SET work_mode_id = (SELECT id FROM work_modes WHERE name = 'basic') "
    "WHERE work_mode_id IS NULL"
)
