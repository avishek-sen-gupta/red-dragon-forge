"""Ask whether a program point can be reached with given field values."""

from collections.abc import Callable, Mapping, Sequence

import z3
from cobble.experimental.horn.atoms import comparison
from cobble.experimental.horn.condition import Condition
from cobble.experimental.horn.lower import HornSystem, states
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.solve import solve
from cobble.experimental.horn.terms import conjunction, every, holds
from cobble.experimental.horn.tracked import Tracked
from cobble.experimental.horn.verdict import Verdict


def _condition(
    condition: Condition, state: Mapping[str, z3.SeqRef], fields: Mapping[str, Tracked]
) -> tuple[z3.BoolRef, ...]:
    if condition.field not in fields:
        raise ValueError(f"{condition.field} is not a tracked field")
    terms = comparison(
        condition.field, condition.op.value, condition.value, state, fields
    )
    if not terms:
        raise ValueError(f"{condition.value} cannot be compared with {condition.field}")
    return terms


def _arguments(
    relation: z3.FuncDeclRef, entry: Sequence[z3.SeqRef], now: Sequence[z3.SeqRef]
) -> tuple[z3.SeqRef, ...]:
    return (*entry, *now) if relation.arity() > len(now) else tuple(now)


def reaches(
    system: HornSystem,
    point: Point,
    conditions: Sequence[Condition],
    clock: Callable[[], float],
) -> Verdict:
    v = states(system.fields)
    fields = {field.name: field for field in system.fields}
    state = {field.name: now for field, now in zip(system.fields, v.now, strict=True)}
    asked = tuple(t for c in conditions for t in _condition(c, state, fields))
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
