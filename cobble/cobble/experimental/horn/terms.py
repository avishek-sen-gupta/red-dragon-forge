"""Typed constructors over z3, whose own signatures pyright reads as unions of every term."""

from collections.abc import Sequence

import z3


def _boolean(term: z3.ExprRef | z3.Probe | bool, what: str) -> z3.BoolRef:
    if isinstance(term, z3.BoolRef):
        return term
    raise TypeError(f"{what} is not a boolean term")


def holds(relation: z3.FuncDeclRef, *args: z3.ExprRef) -> z3.BoolRef:
    return _boolean(relation(*args), f"{relation.name()}")


def conjunction(*terms: z3.BoolRef) -> z3.BoolRef:
    if not terms:
        return z3.BoolVal(True)
    return _boolean(z3.And(*terms), "a conjunction")


def negation(term: z3.BoolRef) -> z3.BoolRef:
    return _boolean(z3.Not(term), "a negation")


def equal(left: z3.ExprRef, right: z3.ExprRef) -> z3.BoolRef:
    return _boolean(left == right, "an equality")


def every(variables: Sequence[z3.ExprRef], body: z3.BoolRef) -> z3.BoolRef:
    if not variables:
        return body
    return _boolean(z3.ForAll(list(variables), body), "a quantified rule")


def constant(value: bytes) -> z3.BitVecRef:
    term = z3.BitVecVal(int.from_bytes(value, "big"), 8 * len(value))
    if isinstance(term, z3.BitVecRef):
        return term
    raise TypeError(f"{value!r} is not a bit-vector term")


def extract(high: int, low: int, value: z3.BitVecRef) -> z3.BitVecRef:
    term = z3.Extract(high, low, value)
    if isinstance(term, z3.BitVecRef):
        return term
    raise TypeError("an extract is not a bit-vector term")


def concat(*parts: z3.BitVecRef) -> z3.BitVecRef:
    if len(parts) == 1:
        return parts[0]
    term = z3.Concat(*parts)
    if isinstance(term, z3.BitVecRef):
        return term
    raise TypeError("a concatenation is not a bit-vector term")


def bits(name: str, length: int) -> z3.BitVecRef:
    term = z3.BitVec(name, 8 * length)
    if isinstance(term, z3.BitVecRef):
        return term
    raise TypeError(f"{name} is not a bit-vector term")


def nibble(name: str) -> z3.BitVecRef:
    term = z3.BitVec(name, 4)
    if isinstance(term, z3.BitVecRef):
        return term
    raise TypeError(f"{name} is not a bit-vector term")
