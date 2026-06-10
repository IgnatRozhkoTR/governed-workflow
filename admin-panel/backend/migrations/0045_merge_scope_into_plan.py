"""Merge per-sub-phase scope into the plan and drop the scope columns.

Scope used to live in ``workspaces.scope_json`` (a phase-keyed map
``{"3.N": {"must": [...], "may": [...]}}``) with a separate
``workspaces.scope_status`` approval column. Scope now lives inside the plan:
each ``plan_json["execution"][i]`` with id ``"3.N"`` gains a ``"scope"`` key.
Approving the plan is the single approval that also covers scope.

Step 1 backfills the embedded scope from the old map. Step 2 drops both
columns via native ``ALTER TABLE ... DROP COLUMN`` (SQLite >= 3.35), guarded by
a ``PRAGMA table_info`` check for idempotency — same pattern as
``0042_drop_prev_phase_sequence.py``. The rollback re-adds the columns (empty)
so the migration is reversible at the schema level.
"""
import json

from yoyo import step

_DROP_COLUMNS = ["scope_status", "scope_json"]


def _parse_json(raw, fallback):
    if not raw:
        return fallback
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _embed_scope(plan, scope_map):
    """Write each execution item's scope from the legacy phase-keyed map."""
    execution = plan.get("execution")
    if not isinstance(execution, list):
        return plan
    for item in execution:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        entry = scope_map.get(item_id) if isinstance(scope_map, dict) else None
        item["scope"] = entry if isinstance(entry, dict) else {"must": [], "may": []}
    return plan


def backfill_scope_into_plan(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    columns = {row[1] for row in cursor.fetchall()}
    if "scope_json" not in columns:
        return

    rows = cursor.execute("SELECT id, scope_json, plan_json FROM workspaces").fetchall()
    for ws_id, scope_raw, plan_raw in rows:
        plan = _parse_json(plan_raw, {})
        scope_map = _parse_json(scope_raw, {})
        updated = _embed_scope(plan, scope_map)
        cursor.execute(
            "UPDATE workspaces SET plan_json = ? WHERE id = ?",
            (json.dumps(updated), ws_id),
        )


def drop_scope_columns(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}
    for column_name in _DROP_COLUMNS:
        if column_name in existing:
            cursor.execute(f"ALTER TABLE workspaces DROP COLUMN {column_name}")


def readd_scope_columns(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workspaces)")
    existing = {row[1] for row in cursor.fetchall()}
    if "scope_json" not in existing:
        cursor.execute("ALTER TABLE workspaces ADD COLUMN scope_json TEXT DEFAULT '{}'")
    if "scope_status" not in existing:
        cursor.execute("ALTER TABLE workspaces ADD COLUMN scope_status TEXT NOT NULL DEFAULT 'pending'")


step(backfill_scope_into_plan)
step(drop_scope_columns, readd_scope_columns)
