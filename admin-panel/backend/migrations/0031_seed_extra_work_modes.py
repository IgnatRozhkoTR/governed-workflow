"""Seed two additional system work-mode presets: ``lite`` and ``solo``.

``lite``  — Workflow without the final blind review pass (phases 4.0, 4.1, 4.2
            disabled).
``solo``  — Solo workflow with the user-approval gates skipped: the static
            preparation-review (1.4), the templated per-item commit-approval
            family (3.x.3) — which disables every concrete 3.N.3 — and the
            final-approval gate (4.2). The agent-only phases (verification,
            fix review, agentic review) are left enabled.

The disabled set is split into ``static`` (concrete, non-templated registry
ids) and ``templated`` (3.x.K family ids) so the templated entries land in
``work_mode_phases`` even though the canonical seeding loop iterates only
non-templated ids.

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
            "static_disabled": {"4.0", "4.1", "4.2"},
            "templated_disabled": set(),
        },
        {
            "name": "solo",
            "description": (
                "Solo workflow with user-approval gates skipped "
                "(preparation review, per-item commit approval, final approval)"
            ),
            "static_disabled": {"1.4", "4.2"},
            "templated_disabled": {"3.x.3"},
        },
    ]

    for mode in modes:
        unknown_static = mode["static_disabled"] - set(canonical_ids)
        if unknown_static:
            raise RuntimeError(
                f"Mode {mode['name']!r}: static_disabled references unknown phase ids: {sorted(unknown_static)}"
            )
        unknown_templated = mode["templated_disabled"] - set(PHASE_REGISTRY)
        if unknown_templated:
            raise RuntimeError(
                f"Mode {mode['name']!r}: templated_disabled references unknown phase ids: {sorted(unknown_templated)}"
            )

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

        position = 0
        for phase_id in canonical_ids:
            enabled = 0 if phase_id in mode["static_disabled"] else 1
            cursor.execute(
                "INSERT INTO work_mode_phases (work_mode_id, phase_id, enabled, position) "
                "VALUES (?, ?, ?, ?)",
                (mode_id, phase_id, enabled, position),
            )
            position += 1

        for templated_id in sorted(mode["templated_disabled"], key=phase_key):
            cursor.execute(
                "INSERT INTO work_mode_phases (work_mode_id, phase_id, enabled, position) "
                "VALUES (?, ?, 0, ?)",
                (mode_id, templated_id, position),
            )
            position += 1


step(seed_extra_modes)
