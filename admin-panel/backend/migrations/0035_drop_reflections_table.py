"""Drop the reflections table.

The reflection feature is being reimagined as an end-of-ticket phase that
produces proposals; we no longer persist standalone reflection nodes.
"""
from yoyo import step

step("DROP INDEX IF EXISTS idx_reflections_workspace")
step("DROP TABLE IF EXISTS reflections")
