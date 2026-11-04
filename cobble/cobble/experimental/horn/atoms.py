"""A comparison as a z3 term, when both its sides are values the encoding follows exactly."""

from collections.abc import Mapping

import z3
from cobble.experimental.horn.terms import constant, equal, negation
from cobble.experimental.horn.tracked import COMPARISONS, Tracked

FIGURATIVES: Mapping[str, str] = {
    "SPACE": " ",
    "SPACES": " ",
    "LOW-VALUE": "\x00",
    "LOW-VALUES": "\x00",
    "HIGH-VALUE": "\xff",
    "HIGH-VALUES": "\xff",
    "ZERO": "0",
    "ZEROS": "0",
    "ZEROES": "0",
}

QUOTES = ("'", '"')


def quoted(value: str) -> bool:
    return len(value) >= 2 and value[0] in QUOTES and value[-1] == value[0]


def unquoted(value: str) -> str:
    return value[1:-1].replace(value[0] * 2, value[0])


def _literal(value: str, length: int) -> tuple[z3.BitVecRef, ...]:
    inner = unquoted(value)
    return (constant(inner.ljust(length)),) if len(inner) <= length else ()


def _field(
    value: str,
    length: int,
    state: Mapping[str, z3.BitVecRef],
    fields: Mapping[str, Tracked],
) -> tuple[z3.BitVecRef, ...]:
    same = value in fields and fields[value].length == length
    return (state[value],) if same else ()


def operand(
    value: str,
    length: int,
    state: Mapping[str, z3.BitVecRef],
    fields: Mapping[str, Tracked],
) -> tuple[z3.BitVecRef, ...]:
    if quoted(value):
        return _literal(value, length)
    if value in FIGURATIVES:
        return (constant(FIGURATIVES[value] * length),)
    return _field(value, length, state, fields)


def comparison(
    left: str,
    op: str,
    right: str,
    state: Mapping[str, z3.BitVecRef],
    fields: Mapping[str, Tracked],
) -> tuple[z3.BoolRef, ...]:
    if op not in COMPARISONS or left not in fields:
        return ()
    same = tuple(
        equal(state[left], value)
        for value in operand(right, fields[left].length, state, fields)
    )
    return same if op == "==" else tuple(negation(term) for term in same)
