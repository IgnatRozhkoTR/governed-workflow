"""Discover and register module-contributed phases from phase.yaml manifests.

Each module directory (under claude/modules/ or claude/modules-local/) MAY contain:
- phase.yaml: declarative manifest describing contributed phases
- phase_factory.py: optional Python module exposing validator callables

Modules without phase.yaml contribute no phases. Invalid manifests are logged
and skipped, never fatal. If PyYAML is unavailable the loader degrades to a
no-op so the server can start without the optional dependency.
"""
import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SUPPORTED_BANDS = ("preparation", "finalization")


def load_module_phases(module_dirs: list[Path]) -> list:
    """Scan each module dir for phase.yaml + optional phase_factory.py.

    Returns a list of DeclarativePhase instances. Phases with unsupported
    bands (execution, planning) are skipped with a warning.
    """
    from advance.phases.declarative import DeclarativePhase

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed; module-contributed phases disabled.")
        return []

    phases = []
    for mod_dir in module_dirs:
        manifest_path = mod_dir / "phase.yaml"
        if not manifest_path.is_file():
            continue

        manifest = _load_manifest(yaml, manifest_path)
        if manifest is None:
            continue

        factory_module = _load_factory(mod_dir / "phase_factory.py")

        for entry in manifest.get("phases", []) or []:
            phase = _build_phase(mod_dir, entry, factory_module, DeclarativePhase)
            if phase is not None:
                phases.append(phase)

    return phases


def _load_manifest(yaml_module, manifest_path: Path) -> dict | None:
    try:
        data = yaml_module.safe_load(manifest_path.read_text()) or {}
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", manifest_path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("Manifest %s is not a mapping; skipping.", manifest_path)
        return None
    return data


def _build_phase(mod_dir: Path, entry: dict, factory_module, declarative_cls):
    phase_id = entry.get("id")
    if not phase_id:
        logger.warning("Module %s: phase entry missing 'id'; skipping.", mod_dir.name)
        return None

    band = entry.get("band", "preparation")
    if band not in _SUPPORTED_BANDS:
        logger.warning(
            "Module %s phase %s: unsupported band %r (skipping)",
            mod_dir.name, phase_id, band,
        )
        return None

    validator_fn = _resolve_validator(mod_dir, entry.get("validator"), factory_module)

    try:
        position = int(entry.get("position", 1000))
    except (TypeError, ValueError):
        logger.warning(
            "Module %s phase %s: invalid position %r; defaulting to 1000.",
            mod_dir.name, phase_id, entry.get("position"),
        )
        position = 1000

    return declarative_cls(
        manifest=entry,
        validator_fn=validator_fn,
        band=band,
        position=position,
    )


def _resolve_validator(mod_dir: Path, validator_name, factory_module):
    if not validator_name:
        return None
    if factory_module is None:
        logger.warning(
            "Module %s: validator %r declared but no phase_factory.py loaded",
            mod_dir.name, validator_name,
        )
        return None
    fn = getattr(factory_module, validator_name, None)
    if fn is None:
        logger.warning(
            "Module %s: validator %r not found in phase_factory.py",
            mod_dir.name, validator_name,
        )
    return fn


def _load_factory(factory_path: Path):
    if not factory_path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            f"module_phase_factory_{factory_path.parent.name}",
            factory_path,
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        logger.warning("Failed to load %s: %s", factory_path, exc)
        return None
