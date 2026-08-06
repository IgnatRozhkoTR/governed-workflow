#!/usr/bin/env python3
"""Stop hook: executes the pending advance action after a major-phase transition.

workspace_advance (Task D) writes <cwd>/.claude/state/pending-advance-action
containing either 'compact' or 'clear'. This hook reads that file and acts:
  compact — trigger /compact in the current tmux pane (context-window reset).
  clear   — write a force-new-session flag then send /exit so the launch
             wrapper (Task C) relaunches Claude without --continue.
"""
import json
import logging
import os
import subprocess
import sys
import time

# ─── Logging ────────────────────────────────────────────────────────────────

handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("%(levelname)s [stop-advance-action] %(message)s"))
logger = logging.getLogger("stop-advance-action")
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ─── Parse stdin envelope ────────────────────────────────────────────────────

try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, EOFError):
    data = {}

cwd = data.get("cwd", os.getcwd())

# ─── Locate action file ──────────────────────────────────────────────────────

STATE_DIR = os.path.join(cwd, ".claude", "state")
ACTION_FILE = os.path.join(STATE_DIR, "pending-advance-action")

if not os.path.exists(ACTION_FILE):
    sys.exit(0)

# ─── Read and validate action ────────────────────────────────────────────────

try:
    action = open(ACTION_FILE).read().strip()
except OSError as exc:
    logger.warning("could not read action file %s: %s", ACTION_FILE, exc)
    sys.exit(0)

KNOWN_ACTIONS = ("compact", "clear")
if action not in KNOWN_ACTIONS:
    logger.warning("unknown action %r in %s — ignoring", action, ACTION_FILE)
    os.remove(ACTION_FILE)
    sys.exit(0)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def tmux_pane():
    pane = os.environ.get("TMUX_PANE", "")
    return pane if pane else None


def delete_action_file():
    try:
        os.remove(ACTION_FILE)
    except OSError as exc:
        logger.warning("could not delete action file: %s", exc)


def send_tmux_keys(pane, keys):
    result = subprocess.run(
        ["tmux", "send-keys", "-t", pane, keys, "Enter"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "tmux send-keys failed (pane=%s, keys=%r): %s",
            pane, keys, result.stderr.strip()
        )

# ─── compact ─────────────────────────────────────────────────────────────────

if action == "compact":
    pane = tmux_pane()
    if pane is None:
        logger.warning(
            "TMUX_PANE unset — cannot send /compact (user not in a tmux session); "
            "skipping compact action"
        )
        delete_action_file()
        sys.exit(0)

    send_tmux_keys(pane, "/compact")
    time.sleep(0.5)
    send_tmux_keys(pane, "Continue with the next phase.")
    delete_action_file()
    sys.exit(0)

# ─── clear ───────────────────────────────────────────────────────────────────

if action == "clear":
    pane = tmux_pane()
    if pane is None:
        logger.warning(
            "TMUX_PANE unset — cannot send /exit or write force-new-session flag "
            "(user not in a tmux session); skipping clear action"
        )
        delete_action_file()
        sys.exit(0)

    flag_file = os.path.join(STATE_DIR, "force-new-session")
    kickoff_file = os.path.join(STATE_DIR, "kickoff-pending")
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        open(flag_file, "w").close()
        # Signal the admin panel's session-start handler to auto-submit a
        # continue prompt once the relaunched session is ready. Without it the
        # cleared session restarts but waits idle for human input.
        open(kickoff_file, "w").close()
    except OSError as exc:
        logger.warning("could not write clear-action flags: %s", exc)

    delete_action_file()
    send_tmux_keys(pane, "/exit")
    sys.exit(0)
