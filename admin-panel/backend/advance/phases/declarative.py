"""DeclarativePhase -- a Phase driven by a YAML manifest + optional Python validator.

Module-contributed phases use this class instead of subclassing Phase directly.
Identity, gate behavior, and approve/reject targets come from the manifest;
validation delegates to an optional callable loaded from the module's
phase_factory.py. Sequence position is derived from the phase id itself via
``phase_key``, so authors position a phase by choosing an appropriate id (for
example ``"1.5"`` sits between 1.4 and 2.0 automatically).
"""
from advance.phases import Phase


class DeclarativePhase(Phase):
    """A Phase whose configuration is data-driven rather than code-driven."""

    def __init__(self, manifest: dict, validator_fn=None):
        self._id = manifest["id"]
        self._name = manifest.get("name", self._id)
        self._is_user_gate = bool(manifest.get("is_user_gate", False))
        self._approve_target = manifest.get("approve_target")
        self._reject_target = manifest.get("reject_target")
        self._validator_fn = validator_fn
        self._description_for_skill = manifest.get("description_for_skill", "")
        self._short_description = manifest.get("short_description", "")

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def is_user_gate(self):
        return self._is_user_gate

    @property
    def approve_target(self):
        return self._approve_target

    @property
    def reject_target(self):
        return self._reject_target

    def description_for_skill(self, simple_planning: bool = False, workflow_mode: str = "standard") -> str:
        return self._description_for_skill

    @property
    def short_description(self) -> str:
        return self._short_description

    def validate(self, ws, body, project_path):
        if self._validator_fn is None:
            return True, {}
        return self._validator_fn(ws, body, project_path)

    def next_phase(self, ws):
        """Return the approve/reject target when declared, else the phase's own id.

        Returning the phase's own id lets the orchestrator's forward resolver
        walk onward through the spliced sequence, deriving "next" from the
        sequence instead of a fragile empty-string sentinel.
        """
        return self._approve_target or self._reject_target or self._id
