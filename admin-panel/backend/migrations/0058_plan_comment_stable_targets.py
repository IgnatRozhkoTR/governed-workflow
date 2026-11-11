"""Rewrite plan comment targets from translated labels to stable keys.

The plan view used to store targets such as 'Entire plan' / 'Весь план',
'Sub-phase: 1.1 Name' / 'Под-фаза: 1.1 Name' and 'Task: Title'. It now stores
'plan', 'subphase:<id>' and 'task:<title>'. Targets already in the new form
or in any other form are left untouched, so re-running is a no-op, and
installs without a discussions table are skipped.
"""
import re

from yoyo import step

ENTIRE_PLAN_LABELS = ("Entire plan", "Весь план")
SUBPHASE_LABEL = re.compile(r"^(?:Sub-phase|Под-фаза): (\S+)(?: .*)?$", re.DOTALL)
TASK_LABEL_PREFIX = "Task: "


def stable_target(old_target):
    if old_target in ENTIRE_PLAN_LABELS:
        return "plan"
    subphase = SUBPHASE_LABEL.match(old_target)
    if subphase:
        return "subphase:" + subphase.group(1)
    if old_target.startswith(TASK_LABEL_PREFIX):
        return "task:" + old_target[len(TASK_LABEL_PREFIX):]
    return old_target


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'discussions'")
    if cursor.fetchone() is None:
        return
    cursor.execute("SELECT id, target FROM discussions WHERE scope = 'plan' AND target IS NOT NULL")
    for row_id, old_target in cursor.fetchall():
        new_target = stable_target(old_target)
        if new_target != old_target:
            cursor.execute("UPDATE discussions SET target = ? WHERE id = ?", (new_target, row_id))


step(apply_step)
