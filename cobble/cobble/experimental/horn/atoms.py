"""A comparison as a z3 term over tracked bytes, when both its sides are bytes the encoding knows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

import z3
from cobble.experimental.horn.storage import COMPARISONS, Storage
from cobble.experimental.horn.terms import constant, equal, negation

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
) -> tuple[z3.BoolRef, ...]:
    if op not in COMPARISONS:
        return ()
    same = tuple(
        equal(storage.value(extent, state), value)
        for extent in storage.tracked(left)
        for value in operand(right, extent.length, storage, state)
    )
    return same if op == "==" else tuple(negation(term) for term in same)
