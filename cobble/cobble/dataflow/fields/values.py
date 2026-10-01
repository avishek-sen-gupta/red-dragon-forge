"""A set of concrete byte values an extent can hold, and why it may be incomplete."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MAX_VALUES = 32


class UnresolvedReason(Enum):
    """Why a value set is a subset of what its extent can really hold."""

    NOT_A_LITERAL = "not-a-literal"
    INBOUND_LINKAGE = "inbound-linkage"
    FROM_FILE = "from-file"
    FROM_CALLEE = "from-callee"
    NO_EXTENT = "no-extent"
    UNINITIALISED = "uninitialised"
    OVER_BUDGET = "over-budget"
    INCOMPLETE_WALK = "incomplete-walk"
    UNMODELLED = "unmodelled"


@dataclass(frozen=True)
class ValueSet:
    """Every byte value reaching one extent, and why the set may be short.

    ``reasons`` empty means the set is complete -- these values and no others.
    Non-empty means at least these and possibly more, which is ``Reaching``'s
    truncated/abandoned distinction rather than a top element: collapsing to top
    would discard values already proven, and a caller that wants to know whether a
    site resolved needs the values *and* the doubt, not one or the other.
    """

    values: frozenset[bytes] = frozenset()
    reasons: frozenset[UnresolvedReason] = frozenset()

    @property
    def complete(self) -> bool:
        return not self.reasons


EMPTY = ValueSet()


def bounded(values: frozenset[bytes], reasons: frozenset[UnresolvedReason]) -> ValueSet:
    """``values`` capped at ``MAX_VALUES``, the overflow named rather than hidden.

    Sorted before truncation so a corpus run writes the same artefact on every
    machine; an arbitrary 32 of a frozenset would not.
    """
    if len(values) <= MAX_VALUES:
        return ValueSet(values=values, reasons=reasons)
    return ValueSet(
        values=frozenset(sorted(values)[:MAX_VALUES]),
        reasons=reasons | {UnresolvedReason.OVER_BUDGET},
    )


def merged(left: ValueSet, right: ValueSet) -> ValueSet:
    return bounded(left.values | right.values, left.reasons | right.reasons)


def of_value(value: bytes) -> ValueSet:
    return ValueSet(values=frozenset({value}))


def because(reason: UnresolvedReason) -> ValueSet:
    return ValueSet(reasons=frozenset({reason}))


def fitted(value: bytes, width: int) -> bytes:
    """One value as it lands in a ``width``-byte alphanumeric field.

    Truncated on the right when longer and space-filled when shorter, which is what
    an alphanumeric MOVE does: PIC X(4) VALUE 'ABCDEFGH' holds ABCD, and MOVE 'CO'
    into a PIC X(8) leaves six spaces. A value of any other length would claim bytes
    its extent does not own.
    """
    return value[:width].ljust(width, b" ")


def refitted(source: ValueSet, width: int) -> ValueSet:
    return bounded(
        frozenset(fitted(value, width) for value in source.values), source.reasons
    )
