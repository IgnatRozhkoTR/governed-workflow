"""Seed two additional system work-mode presets: ``lite`` and ``solo``.

``lite``  — Workflow without the final blind review pass (phases 4.0, 4.1, 4.2
            disabled).
``solo``  — Solo workflow with user gates skipped (phases 1.4, 3.1, 4.2
            disabled).

Idempotent: re-runs are no-ops if either row already exists (checked by name).
Uses the same pattern as ``0029_work_modes.py`` — no DDL; tables already exist.
"""
from yoyo import step


def seed_extra_modes(conn):
    from advance.phases import PHASE_REGISTRY
    from core.phase import is_templated, phase_key

    canonical_ids = sorted(
        (pid for pid in PHASE_REGISTRY.keys() if not is_templated(pid)),
        key=phase_key,
    )

    modes = [
        {
            "name": "lite",
            "description": "Workflow without the final blind review pass",
            "disabled": {"4.0", "4.1", "4.2"},
        },
        {
            "name": "solo",
            "description": "Solo workflow with user gates skipped",
            "disabled": {"1.4", "3.1", "4.2"},
        },
    ]

    cursor = conn.cursor()
    for mode in modes:
        cursor.execute("SELECT id FROM work_modes WHERE name = ?", (mode["name"],))
        if cursor.fetchone() is not None:
            continue

        cursor.execute(
            "INSERT INTO work_modes (name, description, origin) "
            "VALUES (?, ?, 'system')",
            (mode["name"], mode["description"]),
        )
        mode_id = cursor.lastrowid

        for position, phase_id in enumerate(canonical_ids):
            enabled = 0 if phase_id in mode["disabled"] else 1
            cursor.execute(
                "INSERT INTO work_mode_phases (work_mode_id, phase_id, enabled, position) "
                "VALUES (?, ?, ?, ?)",
                (mode_id, phase_id, enabled, position),
            )


step(seed_extra_modes)
