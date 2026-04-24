# Advance

Phase gate logic — the most complex subsystem in the server.

## Architecture

Each workflow sub-phase is a `Phase` subclass (in `phases/`) that encapsulates its identity, validation, and advancement logic. The orchestrator drives the phase lifecycle generically — no hardcoded phase strings.

## Packages

- `phases/` — Phase ABC and concrete phase definitions
  - `preparation.py` — phases 0 through 1.4 (init, assessment, research, proving, impact, preparation review gate)
  - `planning.py` — phase 2.0 (plan validation)
  - `execution.py` — phases 3.N.0 through 3.N.4 (parameterized by execution item N)
  - `finalization.py` — phases 4.0 through 5 (blind review, address fixes, final approval gate, done)
  - `declarative.py` — module-contributed phases (e.g. 2.1 Plan Review gate)

- `orchestrator.py` — `perform_advance()`, `approve_gate()`, `reject_gate()`, `transition_phase()`.
- `guards.py` — cross-cutting `AdvanceGuard` classes that self-select by phase.
- `permissions.py` — tool permission enforcement during phases.
- `validators.py` — programmatic acceptance criteria validation.
