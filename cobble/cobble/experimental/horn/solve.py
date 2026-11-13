"""Ask Z3 Spacer whether a goal is derivable from a set of Horn rules."""

import logging
from collections.abc import Callable, Mapping, Sequence

import z3
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.verdict import Verdict

logger = logging.getLogger(__name__)

QUERY_TIMEOUT_MS = 180_000
CANCELED = "canceled"

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
    timeout_ms: int = QUERY_TIMEOUT_MS,
) -> Verdict:
    """UNKNOWN when Spacer gives up, or when the query runs past ``timeout_ms``,
    which Spacer reports by raising rather than answering."""
    fixedpoint = z3.Fixedpoint()
    fixedpoint.set(engine="spacer", timeout=timeout_ms)
    fixedpoint.register_relation(*relations)
    for rule in rules:
        fixedpoint.add_rule(rule)
    start = clock()
    result = _answer(fixedpoint, goal)
    seconds = clock() - start
    logger.info(
        "%d rules, %d relations: %s in %.3fs",
        len(rules),
        len(relations),
        result,
        seconds,
    )
    return Verdict(result, seconds)


def _answer(fixedpoint: z3.Fixedpoint, goal: z3.BoolRef) -> Answer:
    try:
        return ANSWERS[str(fixedpoint.query(goal))]
    except z3.Z3Exception as error:
        if CANCELED not in str(error.value):
            raise
        return Answer.UNKNOWN
