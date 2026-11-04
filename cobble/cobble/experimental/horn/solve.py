"""Ask Z3 Spacer whether a goal is derivable from a set of Horn rules."""

import logging
from collections.abc import Callable, Mapping, Sequence

import z3
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.verdict import Verdict

logger = logging.getLogger(__name__)

ANSWERS: Mapping[str, Answer] = {
    "sat": Answer.SAT,
    "unsat": Answer.UNSAT,
    "unknown": Answer.UNKNOWN,
}


def solve(
    rules: Sequence[z3.BoolRef],
    relations: Sequence[z3.FuncDeclRef],
    goal: z3.BoolRef,
    clock: Callable[[], float],
) -> Verdict:
    fixedpoint = z3.Fixedpoint()
    fixedpoint.set(engine="spacer")
    fixedpoint.register_relation(*relations)
    for rule in rules:
        fixedpoint.add_rule(rule)
    start = clock()
    result = fixedpoint.query(goal)
    seconds = clock() - start
    logger.info(
        "%d rules, %d relations: %s in %.3fs",
        len(rules),
        len(relations),
        result,
        seconds,
    )
    return Verdict(ANSWERS[str(result)], seconds)
