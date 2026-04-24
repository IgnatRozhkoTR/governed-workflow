"""Phase string comparison utilities.

Used by services and other packages that need to compare phase strings
without depending on the advance package. The Phase ABC in advance/phases/
owns the full comparison behavior for Phase objects.
"""


def _component_key(component: str) -> tuple[int, int, str]:
    """Return a sort key for a single dotted-phase component.

    Numeric components sort before non-numeric ones so module phases like
    "mod.prep.x" never crash a comparison. Numeric components use their
    integer value; non-numeric components use a sentinel that places them
    after all numerics, then fall back to lexicographic order.
    """
    try:
        return (0, int(component), "")
    except ValueError:
        return (1, 0, component)


def phase_key(phase_str: str) -> tuple[tuple[int, int, str], ...]:
    """Parse a dotted phase string into a comparable tuple.

    Numeric components compare by integer value; non-numeric components
    (e.g. from module-contributed phase ids) sort after numeric ones by
    lexicographic fallback.

    >>> phase_key("3.1.4") < phase_key("3.2.0")
    True
    >>> phase_key("mod.prep.x")  # does not raise
    ((1, 0, 'mod'), (0, 0, ''), (1, 0, 'prep'), (1, 0, 'x'))
    """
    return tuple(_component_key(x) for x in phase_str.split('.'))


def is_templated(phase_id: str) -> bool:
    """Return True when any dotted segment of ``phase_id`` is the literal ``x``.

    Templated ids describe a family of concrete phases parameterized by plan
    data. The empty string has no segments and is not templated.
    """
    if not phase_id:
        return False
    return any(segment == "x" for segment in phase_id.split("."))
