"""Renumber the Done phase id from '5' to '6'.

Stage 3 inserted 5.1 Reflection and 5.2 Manual implementation between
4.2 Final approval and Done. The phase classes were renumbered in code,
but rows in tables that store phase IDs as strings still reference '5'.
This migration updates them in-place.
"""
from yoyo import step

step("UPDATE work_mode_phases SET phase_id = '6' WHERE phase_id = '5'")
step("UPDATE phase_settings SET phase_id = '6' WHERE phase_id = '5'")
