"""Discover and register module-contributed MCP tools from mcp_module.py.

Each module directory (under claude/modules/ or claude/modules-local/) MAY
contain an ``mcp_module.py`` exposing a ``register(mcp) -> None`` function.
Modules without ``mcp_module.py`` contribute no tools. Only enabled modules
(per the ``modules_enabled`` table) are considered.

The file is deliberately named ``mcp_module.py`` and not ``mcp_tools.py``:
the backend already ships an ``mcp_tools/`` package, and adding a module
directory to ``sys.path`` (or resolving name collisions carelessly) could
shadow it. Loading is done via ``importlib.util.spec_from_file_location``
under a unique module name so no such collision is possible.

A module whose ``mcp_module.py`` fails to import, or whose ``register()``
raises, is logged and skipped — never fatal, since a broken module must not
prevent every ``workspace_*`` tool from registering.
"""
import importlib.util
import logging
import sys
from pathlib import Path

from core.db import get_db_ctx
from core.paths import DEFAULT_MODULES_DIR, DEFAULT_MODULES_LOCAL_DIR
from services.modules_discovery import enabled_module_ids, iter_module_dirs

logger = logging.getLogger(__name__)

_MODULE_MCP_ROOTS = [DEFAULT_MODULES_DIR, DEFAULT_MODULES_LOCAL_DIR]


def register_module_mcp_tools(mcp) -> list[str]:
    """Discover enabled modules' mcp_module.py and call register(mcp) on each.

    Returns the ids of modules whose register() call succeeded. A module
    with no mcp_module.py contributes nothing. A module that is not enabled
    (per modules_enabled) is skipped. A module whose mcp_module.py fails to
    import or whose register() raises is logged and skipped — never fatal,
    since a broken module must not prevent every workspace_* tool from
    registering. If the DB itself is unreachable (e.g. no migrations run
    yet), log and return [] — register nothing, but never raise.
    """
    module_dirs_by_id = {
        entry.name: entry
        for entry in iter_module_dirs(_MODULE_MCP_ROOTS, required_file="mcp_module.py")
    }

    try:
        with get_db_ctx() as db:
            ordered_ids = enabled_module_ids(db)
    except Exception as exc:
        logger.warning("Failed to read enabled modules from DB: %s", exc)
        return []

    registered: list[str] = []
    for module_id in ordered_ids:
        mod_dir = module_dirs_by_id.get(module_id)
        if mod_dir is None:
            continue
        if _register_module(mcp, mod_dir):
            registered.append(module_id)

    return registered


def _register_module(mcp, mod_dir: Path) -> bool:
    module_file = mod_dir / "mcp_module.py"
    spec_name = f"module_mcp_{mod_dir.name}"

    try:
        spec = importlib.util.spec_from_file_location(spec_name, module_file)
        if spec is None or spec.loader is None:
            logger.warning("Failed to load %s: invalid module spec.", module_file)
            return False
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.warning("Failed to load %s: %s", module_file, exc)
        sys.modules.pop(spec_name, None)
        return False

    register_fn = getattr(module, "register", None)
    if register_fn is None:
        logger.warning("Module %s: mcp_module.py has no register() function.", mod_dir.name)
        sys.modules.pop(spec_name, None)
        return False

    try:
        register_fn(mcp)
    except Exception as exc:
        logger.warning("Module %s: register(mcp) raised: %s", mod_dir.name, exc)
        sys.modules.pop(spec_name, None)
        return False

    return True
