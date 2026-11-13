"""Ask whether a program point can be reached with given field values."""

from collections.abc import Callable, Sequence

import z3
from cobble.experimental.horn.atoms import literal_bytes
from cobble.experimental.horn.condition import (
    Condition,
    Digits,
    Entered,
    Op,
    Part,
    Took,
    Visited,
)
from cobble.experimental.horn.lower import HornSystem, outcome_byte, states
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.solve import solve
from cobble.experimental.horn.storage import Storage
from cobble.experimental.horn.terms import (
    RAN,
    concat,
    conjunction,
    constant,
    equal,
    every,
    extract,
    holds,
    negation,
)
from cobble.experimental.horn.verdict import Verdict

Asked = Condition | Visited | Took | Entered


def _asked(
    condition: Asked, storage: Storage, state: Sequence[z3.BitVecRef]
) -> z3.BoolRef:
    if isinstance(condition, Took | Entered):
        return _marked(condition, storage, state)
    if isinstance(condition, Visited):
        ran = equal(storage.mark(condition.point, state), RAN)
        return ran if condition.value else negation(ran)
    return _condition(condition, storage, state)


def _marked(
    condition: Took | Entered, storage: Storage, state: Sequence[z3.BitVecRef]
) -> z3.BoolRef:
    if isinstance(condition, Took):
        return equal(
            storage.outcome(condition.test, state), outcome_byte(condition.outcome)
        )
    entries = storage.entries[storage.entered(condition.range)]
    value = constant(bytes((entries.value(condition.call),)))
    return equal(storage.entry(condition.range, state), value)


def _condition(
    condition: Condition, storage: Storage, state: Sequence[z3.BitVecRef]
) -> z3.BoolRef:
    left = _operand(condition.field, storage, state)
    right = _right(condition, left, storage, state)
    if right.size() != left.size():
        raise ValueError(f"{condition.value} cannot be compared with {condition.field}")
    same = equal(left, right)
    return same if condition.op is Op.EQ else negation(same)


def _right(
    condition: Condition,
    left: z3.BitVecRef,
    storage: Storage,
    state: Sequence[z3.BitVecRef],
) -> z3.BitVecRef:
    """A literal's bytes, or their digit halves, compared with a Part, Digits or an
    alphanumeric field; or another field's bytes."""
    value, field = condition.value, condition.field
    digits = isinstance(field, Digits)
    width = left.size() // (4 if digits else 8)
    found = literal_bytes(value, width) if isinstance(value, str) else ()
    if not found:
        return _operand(value, storage, state)
    if isinstance(field, str) and not storage.field(field):
        raise ValueError(f"{value} cannot be compared with {field}")
    literal = constant(found[0])
    return _digit_halves(literal) if digits else literal


def _operand(
    operand: str | Part | Digits, storage: Storage, state: Sequence[z3.BitVecRef]
) -> z3.BitVecRef:
    if isinstance(operand, Digits):
        part = Part(operand.field, operand.start, operand.length)
        return _digit_halves(_bytes(part, storage, state))
    return _bytes(operand, storage, state)


def _digit_halves(value: z3.BitVecRef) -> z3.BitVecRef:
    lows = tuple(8 * k for k in reversed(range(value.size() // 8)))
    return concat(*(extract(low + 3, low, value) for low in lows))


def _bytes(
    operand: str | Part, storage: Storage, state: Sequence[z3.BitVecRef]
) -> z3.BitVecRef:
    name = operand.field if isinstance(operand, Part) else operand
    extents = tuple(e for e in storage.whole(name) if storage.locate(e) >= 0)
    if not extents:
        raise ValueError(f"{name} is not a tracked field")
    whole = storage.value(extents[0], state)
    if isinstance(operand, str):
        return whole
    return _part(operand, extents[0].length, whole)


def _part(part: Part, length: int, whole: z3.BitVecRef) -> z3.BitVecRef:
    first, end = part.start - 1, part.start - 1 + part.length
    if first < 0 or part.length < 1 or end > length:
        raise ValueError(f"{part} is outside {part.field}")
    return extract(8 * (length - first) - 1, 8 * (length - end), whole)


def _arguments(
    relation: z3.FuncDeclRef,
    entry: Sequence[z3.BitVecRef],
    now: Sequence[z3.BitVecRef],
) -> tuple[z3.BitVecRef, ...]:
    return (*entry, *now) if relation.arity() > len(now) else tuple(now)


def reaches(
    system: HornSystem,
    point: Point,
    conditions: Sequence[Asked],
    clock: Callable[[], float],
) -> Verdict:
    storage = system.storages[point.program]
    v = states(storage)
    asked = tuple(_asked(c, storage, v.now) for c in conditions)
    goal = z3.Function("goal", z3.BoolSort())
    rules = tuple(
        every(
            v.variables,
            z3.Implies(
                conjunction(
                    holds(relation, *_arguments(relation, v.entry, v.now)), *asked
                ),
                holds(goal),
            ),
        )
        for relation in system.at[point]
    )
    return solve((*system.rules, *rules), (*system.relations, goal), holds(goal), clock)
