"""Phase definitions for the governed workflow.

Each workflow sub-phase is a Phase subclass that encapsulates:
- Identity: id, name
- Gate behavior: is_user_gate, approve_target, reject_target
- Advancement: validate(), next_phase(), progress_key(), success_message()
"""
import re
from abc import ABC, abstractmethod

from core.phase import phase_key


class Phase(ABC):
    """Abstract base for all workflow phases."""

    @property
    @abstractmethod
    def id(self) -> str:
        """Dotted phase identifier, e.g. '1.2' or '3.1.0'."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable phase name."""

    @property
    def boundary_key(self) -> str:
        """The boundary group this phase belongs to.

        Two phases share a boundary group when their boundary_key is equal.
        Transitioning between different boundary groups is a major boundary
        crossing — eligible for per-project compact/clear advance actions.

        Default: the first dotted segment of id (e.g. "1", "2", "4", "5", "6").
        Execution sub-phases (3.N.K) override to return "3.N" so that
        3.1.0→3.1.4 is internal but 3.1.4→3.2.0 crosses a boundary.
        """
        return self.id.split('.')[0]

    @property
    def is_user_gate(self) -> bool:
        """Whether this phase requires explicit user approval to proceed."""
        return False

    @property
    def approve_target(self) -> str | None:
        """Phase to transition to on gate approval. Only for gates."""
        return None

    @property
    def reject_target(self) -> str | None:
        """Phase to transition to on gate rejection. Only for gates."""
        return None

    def on_approve(self, ws, body, db):
        """Hook called during gate approval. Override to save data (e.g., commit message)."""
        pass

    @abstractmethod
    def validate(self, ws, body, project_path) -> tuple:
        """Phase-specific validation. Returns (ok: bool, details: dict)."""

    @abstractmethod
    def next_phase(self, ws) -> str:
        """The phase to advance to after successful validation."""

    def progress_key(self, ws) -> str | None:
        """If not None, a progress entry with this key must exist before advancing."""
        return None

    def description_for_skill(self, simple_planning: bool = False) -> str:
        """Markdown block for this phase, rendered into SKILL.md.
        Empty string means omit from the rendered skill."""
        return ""

    @property
    def short_description(self) -> str:
        """One-line summary of what this phase does, rendered into the Phase Map row.
        Empty string means the phase is omitted from the Phase Map even when enabled."""
        return ""

    def success_message(self, ws, new_phase) -> str:
        """Message returned on successful advance. Override for custom messages."""
        from core.i18n import t

        locale = ws["locale"]
        phase_guides = {
            "1.0": t("phase.guide.1_0", locale),
            "1.1": t("phase.guide.1_1", locale),
            "1.2": t("phase.guide.1_2", locale),
            "1.3": t("phase.guide.1_3", locale),
            "1.4": t("phase.guide.1_4", locale),
            "2.0": t("phase.guide.2_0", locale),
            "4.0": t("phase.guide.4_0", locale),
            "4.1": t("phase.guide.4_1", locale),
            "4.2": t("phase.guide.4_2", locale),
            "5.1": t("phase.guide.5_1", locale),
            "5.2": t("phase.guide.5_2", locale),
            "6": t("phase.guide.6", locale),
        }
        match = re.match(r'^3\.(\d+)\.(\d+)$', new_phase)
        if match:
            n, k = match.group(1), match.group(2)
            sub_guides = {
                "0": t("phase.guide.sub.0", locale),
                "1": t("phase.guide.sub.1", locale, n=n),
                "2": t("phase.guide.sub.2", locale),
                "3": t("phase.guide.sub.3", locale),
                "4": t("phase.guide.sub.4", locale, n=n),
            }
            guide = sub_guides.get(k, "")
            if guide:
                return t("advance.success.advancedWithGuide", locale, phase=new_phase, guide=guide)
            return t("advance.success.advanced", locale, phase=new_phase)

        guide = phase_guides.get(new_phase, "")
        if guide:
            return t("advance.success.advancedWithGuide", locale, phase=new_phase, guide=guide)
        return t("advance.success.advanced", locale, phase=new_phase)

    def __lt__(self, other):
        a = phase_key(self.id)
        b = phase_key(other.id if isinstance(other, Phase) else str(other))
        return a < b

    def __le__(self, other):
        return self == other or self < other

    def __gt__(self, other):
        a = phase_key(self.id)
        b = phase_key(other.id if isinstance(other, Phase) else str(other))
        return a > b

    def __ge__(self, other):
        return self == other or self > other

    def __eq__(self, other):
        if isinstance(other, Phase):
            return self.id == other.id
        return self.id == str(other)

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f"{self.__class__.__name__}('{self.id}')"


# Phase registry -- populated by submodule imports below
PHASE_REGISTRY: dict[str, Phase] = {}


def register_phase(phase: Phase):
    """Register a phase instance in the global registry."""
    PHASE_REGISTRY[phase.id] = phase


def get_phase(phase_str: str) -> Phase | None:
    """Look up a Phase by its dotted string ID.

    For concrete execution phases (3.N.K) the parameterized instance is built
    on demand; registered entries (including 3.x.K templates) are returned
    verbatim so templates never masquerade as runnable phases.
    """
    if phase_str in PHASE_REGISTRY:
        return PHASE_REGISTRY[phase_str]

    # Dynamic execution phases: 3.N.K
    m = re.match(r'^3\.(\d+)\.(\d+)$', phase_str)
    if m:
        from advance.phases.execution import get_execution_phase
        return get_execution_phase(int(m.group(1)), int(m.group(2)))

    return None


# Import and register all static phases
from advance.phases.preparation import PHASES as _prep_phases  # noqa: E402
from advance.phases.planning import PHASES as _plan_phases  # noqa: E402
from advance.phases.finalization import PHASES as _final_phases  # noqa: E402

for _phase in _prep_phases + _plan_phases + _final_phases:
    register_phase(_phase)

# Importing ``execution`` has the side effect of registering the 3.x.K
# template phases into ``PHASE_REGISTRY`` so the sequencer can expand them.
import advance.phases.execution  # noqa: E402,F401


# Module-contributed phase registration is explicit: app startup (or tests)
# must invoke register_module_phases_from_disk(). Running at import time made
# behavior depend on the module directories that happened to exist on disk
# when PHASE_REGISTRY was first imported, leaking filesystem state into tests.
_MODULE_PHASE_IDS: set[str] = set()


def register_module_phases_from_disk() -> None:
    """Discover and register DeclarativePhases from the on-disk modules roots.

    Safe to call multiple times: phases already registered are left in place
    and colliding ids are logged. Newly discovered module phases are tracked
    so ``reset_module_phases`` can remove exactly the phases this function
    introduced without touching the static registry entries.
    """
    import logging

    from core.paths import DEFAULT_MODULES_DIR, DEFAULT_MODULES_LOCAL_DIR
    from services.module_phase_loader import load_module_phases
    from services.modules_discovery import iter_module_dirs

    dirs = iter_module_dirs([DEFAULT_MODULES_DIR, DEFAULT_MODULES_LOCAL_DIR], required_file="phase.yaml")
    log = logging.getLogger(__name__)
    for phase in load_module_phases(dirs):
        if phase.id in PHASE_REGISTRY:
            log.warning("Module phase %s collides with existing phase; skipping", phase.id)
            continue
        register_phase(phase)
        _MODULE_PHASE_IDS.add(phase.id)


def reset_module_phases() -> None:
    """Remove every phase previously registered by ``register_module_phases_from_disk``."""
    for phase_id in list(_MODULE_PHASE_IDS):
        PHASE_REGISTRY.pop(phase_id, None)
    _MODULE_PHASE_IDS.clear()
