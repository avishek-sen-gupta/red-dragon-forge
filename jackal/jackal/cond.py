"""Pure evaluation of JCL COND= step-bypass conditions (IBM semantics)."""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping, Sequence

from jackal.model import (
    AbendMode,
    AllPriorSteps,
    BypassTest,
    CondOp,
    QualifiedStep,
    RcComparison,
    StepCondition,
)
from jackal.results import StepResult

_OPS: Mapping[CondOp, Callable[[int, int], bool]] = {
    CondOp.GT: operator.gt,
    CondOp.GE: operator.ge,
    CondOp.EQ: operator.eq,
    CondOp.NE: operator.ne,
    CondOp.LT: operator.lt,
    CondOp.LE: operator.le,
}


def _tested(test: BypassTest[QualifiedStep], result: StepResult) -> bool:
    return isinstance(test.target, AllPriorSteps) or test.target == result.step


def _true(test: BypassTest[QualifiedStep], executed: Sequence[StepResult]) -> bool:
    compare = _OPS[test.comparison.op]
    return any(
        compare(test.comparison.code, r.return_code)
        for r in executed
        if _tested(test, r)
    )


def should_bypass(
    condition: StepCondition[QualifiedStep],
    end_job_tests: Sequence[RcComparison],
    history: Sequence[StepResult],
) -> bool:
    if condition.abend_mode is AbendMode.ONLY:
        return True
    executed = tuple(r for r in history if r.ran)
    tests = (
        *condition.bypass_tests,
        *(BypassTest[QualifiedStep](c, AllPriorSteps()) for c in end_job_tests),
    )
    return any(_true(t, executed) for t in tests)
