"""A comparison as a z3 term, when both its sides are values the encoding follows exactly."""

from collections.abc import Mapping

import z3
from cobble.experimental.horn.terms import equal, negation, text
from cobble.experimental.horn.tracked import COMPARISONS, Tracked

FIGURATIVES: Mapping[str, str] = {
    "SPACE": " ",
    "SPACES": " ",
    "LOW-VALUE": "\x00",
    "LOW-VALUES": "\x00",
    "HIGH-VALUE": "\xff",
    "HIGH-VALUES": "\xff",
}

QUOTES = ("'", '"')


def _quoted(value: str) -> bool:
    return len(value) >= 2 and value[0] in QUOTES and value[-1] == value[0]


def _literal(value: str, length: int) -> tuple[z3.SeqRef, ...]:
    inner = value[1:-1].replace(value[0] * 2, value[0])
    return (text(inner.ljust(length)),) if len(inner) <= length else ()


def _field(
    value: str,
    length: int,
    state: Mapping[str, z3.SeqRef],
    fields: Mapping[str, Tracked],
) -> tuple[z3.SeqRef, ...]:
    same = value in fields and fields[value].length == length
    return (state[value],) if same else ()


def operand(
    value: str,
    length: int,
    state: Mapping[str, z3.SeqRef],
    fields: Mapping[str, Tracked],
) -> tuple[z3.SeqRef, ...]:
    if _quoted(value):
        return _literal(value, length)
    if value in FIGURATIVES:
        return (text(FIGURATIVES[value] * length),)
    return _field(value, length, state, fields)


def comparison(
    left: str,
    op: str,
    right: str,
    state: Mapping[str, z3.SeqRef],
    fields: Mapping[str, Tracked],
) -> tuple[z3.BoolRef, ...]:
    if op not in COMPARISONS or left not in fields:
        return ()
    same = tuple(
        equal(state[left], value)
        for value in operand(right, fields[left].length, state, fields)
    )
    return same if op == "==" else tuple(negation(term) for term in same)
