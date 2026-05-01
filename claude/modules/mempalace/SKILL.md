---
name: mempalace
description: Long-term memory provider via MemPalace — enables memory_* MCP tools and the Memory tab in the admin panel.
---

## Overview

This module installs the MemPalace Python package, which exposes `memory_save`,
`memory_retrieve`, `memory_get`, `memory_delete`, and `memory_list` MCP tools to Claude Code sessions.
It also activates the Memory tab in the admin panel, allowing browsing, searching,
and deleting memory entries scoped to a project or ticket.

## Enable

Steps the setup skill executes:

1. Run `bash claude/modules/mempalace/enable.sh` (the setup skill spawns a tmux session and follows these instructions).
2. After install completes, restart the MCP server so the new provider is picked up.

The script will exit with a non-zero status and an `ERROR:` message if Python 3.9+
or pip3 is missing, or if the pip install fails.

## Disable

```bash
pip3 uninstall -y mempalace
```

Restart the MCP server after uninstalling. The Memory tab will return a 503 until
the package is removed from cache or the server is restarted.

## Status

```bash
pip show mempalace
```

A result means installed. "Package(s) not found" means not installed.

## See also

- `claude/modules/telegram/SKILL.md` — multi-session Telegram channel manager.
- Reflection skill (post-3.5): will consume memory promotions produced during reflection runs.
