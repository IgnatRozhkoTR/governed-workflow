"""DeclarativePhase -- a Phase driven by a YAML manifest + optional Python validator.

Module-contributed phases use this class instead of subclassing Phase directly.
Identity, gate behavior, and targets come from the manifest; validation delegates
to an optional callable loaded from the module's phase_factory.py.
"""
from advance.phases import Phase


class DeclarativePhase(Phase):
    """A Phase whose configuration is data-driven rather than code-driven."""

    def __init__(
        self,
        manifest: dict,
        validator_fn=None,
        band: str = "preparation",
        position: int = 1000,
    ):
        self._id = manifest["id"]
        self._name = manifest.get("name", self._id)
        self._is_user_gate = bool(manifest.get("is_user_gate", False))
        self._approve_target = manifest.get("approve_target")
        self._reject_target = manifest.get("reject_target")
        self._validator_fn = validator_fn
        self.band = band
        self.position = position

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

    def validate(self, ws, body, project_path):
        if self._validator_fn is None:
            return True, {}
        return self._validator_fn(ws, body, project_path)

    def next_phase(self, ws):
        # For declarative phases the "next" is determined by the spliced phase
        # sequence in compute_phase_sequence. When no explicit approve/reject
        # target is declared, return a sentinel ("") -- the orchestrator's
        # _resolve_forward_target walks forward through the enabled sequence
        # when the candidate is not in the enabled set, providing a graceful
        # fallback. This is pragmatic; a future revision should derive "next"
        # directly from the sequence rather than through the fallback path.
        return self._approve_target or self._reject_target or ""
