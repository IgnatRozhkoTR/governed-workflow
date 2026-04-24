"""Drop the unused global_flags table.

Migration 0014 introduced ``global_flags`` but no code path ever wrote or
read it. Migration 0024 copied any stray rows into ``device_settings``
under ``flag:<flag_id>`` keys as a safety net, though in practice no such
rows have ever existed. This migration drops the empty table.
"""
from yoyo import step

step("DROP TABLE IF EXISTS global_flags")
