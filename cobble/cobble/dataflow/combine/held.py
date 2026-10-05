"""Held — the values some bytes can hold across programs, and why there may be more."""

from dataclasses import dataclass

from cobble.dataflow.fields.values import UnresolvedReason


@dataclass(frozen=True)
class Held:
    values: frozenset[str] = frozenset()
    reasons: frozenset[UnresolvedReason] = frozenset()
    outside: frozenset[str] = frozenset()


def held_join(left: Held, right: Held) -> Held:
    return Held(
        left.values | right.values,
        left.reasons | right.reasons,
        left.outside | right.outside,
    )
