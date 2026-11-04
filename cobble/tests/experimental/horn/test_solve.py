from collections.abc import Callable, Iterator

import pytest
import z3
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.solve import solve
from cobble.experimental.horn.terms import conjunction, equal, every, holds, negation
from cobble.experimental.horn.verdict import Verdict


def _clock() -> Callable[[], float]:
    ticks: Iterator[float] = iter((1.0, 3.5))
    return lambda: next(ticks)


def _loop(goal_value: Callable[[z3.ArithRef], z3.BoolRef]) -> Verdict:
    n = z3.Int("n")
    at_loop = z3.Function("at_loop", z3.IntSort(), z3.BoolSort())
    at_w = z3.Function("at_w", z3.IntSort(), z3.BoolSort())
    goal = z3.Function("goal", z3.BoolSort())
    rules = (
        holds(at_loop, z3.IntVal(0)),
        every(
            [n],
            z3.Implies(conjunction(holds(at_loop, n), n < 10), holds(at_loop, n + 1)),
        ),
        every([n], z3.Implies(conjunction(holds(at_loop, n), n >= 10), holds(at_w, n))),
        every([n], z3.Implies(conjunction(holds(at_w, n), goal_value(n)), holds(goal))),
    )
    return solve(rules, (at_loop, at_w, goal), holds(goal), _clock())


def _ten(n: z3.ArithRef) -> z3.BoolRef:
    return equal(n, z3.IntVal(10))


def test_an_unreachable_goal_is_unsat() -> None:
    assert _loop(lambda n: negation(_ten(n))) == Verdict(Answer.UNSAT, 2.5)


def test_a_reachable_goal_is_sat() -> None:
    assert _loop(_ten) == Verdict(Answer.SAT, 2.5)


def test_holds_refuses_a_function_that_is_not_a_relation() -> None:
    successor = z3.Function("successor", z3.IntSort(), z3.IntSort())

    with pytest.raises(TypeError, match="^successor is not a boolean term$"):
        holds(successor, z3.IntVal(0))
