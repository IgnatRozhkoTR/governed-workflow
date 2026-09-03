---
name: module-installation
description: How to install a module that contributes MCP tools into governed-workflow — the mcp_module.py convention, where it lands, enabling it, workspace resolution, and the permissions constraint that requires working from inside the governed-workflow repo
user_invocable: false
tools_required:
  - Bash
  - Read
  - Edit
  - Write
---

# Module Installation — Wiring a Module's MCP Tools into the Host

Reference for installing or fixing a `claude/modules(-local)/<name>/` package that
contributes MCP tools to the governed-workflow MCP server. Load this before building
a new module, or before "temporarily" pointing a project's `.mcp.json` at some other
script — that shortcut is not a valid end state, see below.

## The convention

A module that wants to expose MCP tools ships `<module>/mcp_module.py` exporting a
single `register(mcp) -> None` function. The loader is
`admin-panel/backend/services/module_mcp_loader.py`; it is wired into the host at
`admin-panel/backend/mcp_server.py`, called as `register_module_mcp_tools(mcp)`
between `register_module_phases_from_disk()` and `_deregister_simple_mode_tools()`.

The file **must** be named `mcp_module.py`, not `mcp_tools.py` — the backend already
ships an `mcp_tools/` package, and a module directory added to `sys.path` under that
name could shadow it.

The loader only considers **enabled** modules (see below) and never crashes the host:
a module with no `mcp_module.py` contributes nothing; a module whose `mcp_module.py`
fails to import, or whose `register()` raises, is logged and skipped.

## Where a module lands

- `claude/modules-local/<name>/` — local/per-device modules. Git-ignored. Use this
  for anything containing machine-specific paths or credentials.
- `claude/modules/<name>/` — modules meant to ship with the repo. Git-tracked (e.g.
  `telegram/`).

**A standalone sibling `.mcp.json` entry pointing at code outside
`claude/modules(-local)/` is not an acceptable end state.** It's a redundant second
MCP server, invisible to the module-enable/disable UI, and untracked by the host's
own module discovery. If a module was prototyped elsewhere during development (a
scratch/staging directory), it must be relocated into the governed tree and its
`mcp_module.py` wired up before it counts as "installed" — a standalone `.mcp.json`
entry is at best a temporary bring-up step, never the destination.

## Enabling it

Enable the module id (its directory name) via the Setup page / `modules_enabled`
table so `module_mcp_loader` picks it up. Because the loader silently skips disabled
or broken modules (a warning in the log, never a crash), an absent tool set is the
*only* symptom of a broken or forgotten activation step. After enabling:

- Actually call a bare tool from the new module to confirm it round-trips — don't
  just confirm the module "looks enabled."
- Check which `.mcp.json` server key surfaces it. A project's `.mcp.json` can have
  more than one key pointing at the same `mcp_server.py`; confirm the tool shows up
  under the key the session actually uses.

## Host workspace resolution

A module must resolve "which workspace is this call happening in" the same way the
governed tools do: `admin-panel/backend/mcp_tools/__init__.py`'s `_detect_workspace()`
matches `os.getcwd()` (then its parents) against the `workspaces` table's
`working_dir` column.

Do **not** hardcode a static path (e.g. a fixed directory under the user's home) for
anything workspace-scoped — run output, scratch state, generated artifacts. That
breaks the moment the module is used from a second workspace. This is exactly the
mistake made when the `pathway` module was first built: a static `runs_dir` under
`~/.pathway-mcp/`, later fixed to derive from the resolved workspace's `working_dir`.

A module that must also work from its own standalone test suite (which won't have the
host's `core.db` importable) should resolve this lazily and degrade gracefully —
a guard like:

```python
try:
    from core.db import get_db_ctx
except ImportError:
    get_db_ctx = None
```

not a hard dependency declared at module import time.

## The permissions constraint

This is the thing that actually blocks the work if missed. Copying files into
`claude/modules(-local)/`, editing `admin-panel/backend/mcp_server.py` or
`module_mcp_loader.py`, or even just **reading** those files to verify the wiring —
all require a session whose `cwd` is rooted inside the governed-workflow repository.

`admin-panel/backend/advance/permissions.py` (~line 98-123) exempts tool calls only
when `cwd` is inside the governed-workflow install path. Otherwise it blocks:

- Any `Edit`/`Write`/`MultiEdit`/`NotebookEdit` targeting a path inside the
  governed-workflow tree.
- Any `Bash` command whose command string contains the governed-workflow repo's
  absolute path — this covers read-only inspection too (a `cat` or `grep` against a
  file under `admin-panel/`), not just writes. There is no read-only exemption.

Practically: do this work from the orchestrator's own session, or from an agent
explicitly launched with a cwd inside `governed-workflow` — never from a session
rooted in the user's project/workspace directory.

## Verification checklist

Before calling installation done:

- [ ] Module directory sits under `claude/modules/` or `claude/modules-local/` — not
      a sibling of governed-workflow, not left in a scratch/staging location.
- [ ] No standalone `.mcp.json` entry remains pointing outside the governed tree for
      this module's tools.
- [ ] The module is enabled and a bare tool call from it actually round-trips.
- [ ] Workspace-scoped state lands under the *calling workspace's* directory, not a
      static path.
- [ ] The module's own test suite passes, if it has one.
