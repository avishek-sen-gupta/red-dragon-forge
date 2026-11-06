"""A comparison as a z3 term over tracked bytes, when both its sides are bytes the encoding knows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import z3
from cobble.experimental.horn.storage import (
    CALEN_BYTES,
    COMPARISONS,
    EIBCALEN,
    Storage,
    integer,
)
from cobble.experimental.horn.terms import (
    above,
    any_of,
    concat,
    constant,
    equal,
    extract,
    negation,
    nibble_of,
)

FIGURATIVES: Mapping[str, bytes] = MappingProxyType(
    {
        "SPACE": b" ",
        "SPACES": b" ",
        "ZERO": b"0",
        "ZEROS": b"0",
        "ZEROES": b"0",
        "LOW-VALUE": b"\x00",
        "LOW-VALUES": b"\x00",
        "HIGH-VALUE": b"\xff",
        "HIGH-VALUES": b"\xff",
        "QUOTE": b'"',
        "QUOTES": b'"',
    }
)

QUOTES = ("'", '"')
SPACE = b" "
DIGIT_ZONE = 0x3
LAST_DIGIT = 9


@dataclass(frozen=True)
class Branches:
    """What a test's TRUE edge and its FALSE edge each require; nothing, when the
    encoding cannot say."""

    true: tuple[z3.BoolRef, ...] = ()
    false: tuple[z3.BoolRef, ...] = ()


UNKNOWN = Branches()


def literal_bytes(text: str, width: int) -> tuple[bytes, ...]:
    """A literal or figurative as the ``width`` bytes it compares equal to.

    A quoted literal is the fixpoint's bytes (UTF-8, unescaped as the fixpoint
    leaves it) padded with spaces, as an alphanumeric comparison pads the shorter
    side. One longer than the field equals it only if the excess is spaces."""
    word = text.strip()
    if word.upper() in FIGURATIVES:
        return (FIGURATIVES[word.upper()] * width,)
    return _quoted_bytes(word, width)


def _quoted_bytes(word: str, width: int) -> tuple[bytes, ...]:
    if not (len(word) >= 2 and word[0] in QUOTES and word[-1] == word[0]):
        return ()
    raw = word[1:-1].encode("utf-8", errors="replace")
    if raw[width:].strip(SPACE):
        return ()
    return (raw[:width].ljust(width, SPACE),)


def operand(
    text: str, width: int, storage: Storage, state: Sequence[z3.BitVecRef]
) -> tuple[z3.BitVecRef, ...]:
    found = literal_bytes(text, width)
    if found:
        return (constant(found[0]),)
    return tuple(
        storage.value(extent, state)
        for extent in storage.tracked(text)
        if extent.length == width
    )


def comparison(
    left: str,
    op: str,
    right: str,
    storage: Storage,
    state: Sequence[z3.BitVecRef],
) -> Branches:
    if op not in COMPARISONS:
        return UNKNOWN
    found = _compared(left, right, storage, state)
    return found if op == "==" else Branches(found.false, found.true)


def _compared(
    left: str, right: str, storage: Storage, state: Sequence[z3.BitVecRef]
) -> Branches:
    if left == EIBCALEN and storage.eib and integer(right):
        return _calen(int(right), storage, state)
    if integer(right):
        return _counted(left, right, storage, state)
    same = tuple(
        equal(storage.value(extent, state), value)
        for extent in storage.tracked(left)
        for value in operand(right, extent.length, storage, state)
    )
    return Branches(same, tuple(negation(term) for term in same))


def _calen(value: int, storage: Storage, state: Sequence[z3.BitVecRef]) -> Branches:
    if value >= 1 << (8 * CALEN_BYTES - 1):
        return UNKNOWN
    same = equal(storage.calen(state), constant(value.to_bytes(CALEN_BYTES, "big")))
    return Branches((same,), (negation(same),))


def _counted(
    left: str, right: str, storage: Storage, state: Sequence[z3.BitVecRef]
) -> Branches:
    """An unsigned integer field against an integer, by value: its digit halves
    against the integer's digits. A digit half past 9 leaves either edge open, and
    a zone other than a digit's leaves the FALSE edge open too, since a compiler
    may compare such bytes as they stand."""
    extents = tuple(e for e in storage.counted(left) if len(right) <= e.length)
    return next(
        (_numeric(storage.value(e, state), right.zfill(e.length)) for e in extents),
        UNKNOWN,
    )


def _numeric(value: z3.BitVecRef, digits: str) -> Branches:
    lows = tuple(8 * k for k in reversed(range(len(digits))))
    halves = tuple(extract(low + 3, low, value) for low in lows)
    zones = tuple(extract(low + 7, low + 4, value) for low in lows)
    same = equal(concat(*halves), concat(*(nibble_of(int(d)) for d in digits)))
    invalid = any_of(*(above(h, LAST_DIGIT) for h in halves))
    odd = any_of(*(negation(equal(z, nibble_of(DIGIT_ZONE))) for z in zones))
    return Branches((any_of(same, invalid),), (any_of(negation(same), invalid, odd),))
