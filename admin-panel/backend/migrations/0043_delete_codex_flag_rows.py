"""Delete orphaned codex feature-flag rows from device_settings.

The codex subsystem was removed; these two flag keys have no readers or writers
anywhere in the codebase. Deleting non-existent rows is a no-op, so this
migration is inherently idempotent.
"""
from yoyo import step


step("DELETE FROM device_settings WHERE key IN ('flag:codex_enabled', 'flag:codex_phase1_enabled')")
