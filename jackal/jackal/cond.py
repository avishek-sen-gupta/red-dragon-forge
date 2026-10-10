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
    StepReference,
    UnexpandedCall,
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


def _names(reference: StepReference, entry: QualifiedStep | UnexpandedCall) -> bool:
    match entry:
        case QualifiedStep():
            return entry.reference() == reference
        case UnexpandedCall():
            return False


def _tested(test: BypassTest[StepReference], result: StepResult) -> bool:
    match test.target:
        case AllPriorSteps():
            return True
        case _:
            return _names(test.target, result.step)


def _true(test: BypassTest[StepReference], executed: Sequence[StepResult]) -> bool:
    compare = _OPS[test.comparison.op]
    return any(
        compare(test.comparison.code, r.return_code)
        for r in executed
        if _tested(test, r)
    )


def should_bypass(
    condition: StepCondition[StepReference],
    end_job_tests: Sequence[RcComparison],
    history: Sequence[StepResult],
) -> bool:
    if condition.abend_mode is AbendMode.ONLY:
        return True
    executed = tuple(r for r in history if r.ran)
    tests = (
        *condition.bypass_tests,
        *(BypassTest[StepReference](c, AllPriorSteps()) for c in end_job_tests),
    )
    return any(_true(t, executed) for t in tests)
