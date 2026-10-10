"""Pure evaluation of JCL COND= step-bypass conditions (IBM semantics)."""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

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
from jackal.results import AfterJobCond, Bypassed, BypassReason, Flushed, StepResult

_OPS: Mapping[CondOp, Callable[[int, int], bool]] = {
    CondOp.GT: operator.gt,
    CondOp.GE: operator.ge,
    CondOp.EQ: operator.eq,
    CondOp.NE: operator.ne,
    CondOp.LT: operator.lt,
    CondOp.LE: operator.le,
}


@dataclass(frozen=True)
class Run:
    pass


@dataclass(frozen=True)
class _Completed:
    step: QualifiedStep
    rc: int


def _completions(result: StepResult) -> tuple[_Completed, ...]:
    match result.step:
        case QualifiedStep():
            return tuple(_Completed(result.step, rc) for rc in result.outcome.rcs())
        case UnexpandedCall():
            return ()


def _tested(test: BypassTest[StepReference], completed: _Completed) -> bool:
    match test.target:
        case AllPriorSteps():
            return True
        case _:
            return completed.step.reference() == test.target


def _true(test: BypassTest[StepReference], completed: Sequence[_Completed]) -> bool:
    compare = _OPS[test.comparison.op]
    return any(
        compare(test.comparison.code, c.rc) for c in completed if _tested(test, c)
    )


def _meets(tests: Sequence[RcComparison], completed: _Completed) -> bool:
    return any(_OPS[t.op](t.code, completed.rc) for t in tests)


def _own(
    condition: StepCondition[StepReference], completed: Sequence[_Completed]
) -> Run | Bypassed:
    if condition.abend_mode is AbendMode.ONLY:
        return Bypassed(BypassReason.ONLY_WITHOUT_ABEND)
    if any(_true(t, completed) for t in condition.bypass_tests):
        return Bypassed(BypassReason.COND_SATISFIED)
    return Run()


def gate(
    condition: StepCondition[StepReference],
    end_job_tests: Sequence[RcComparison],
    history: Sequence[StepResult],
) -> Run | Bypassed | Flushed:
    completed = tuple(c for r in history for c in _completions(r))
    met = tuple(c for c in completed if _meets(end_job_tests, c))
    if met:
        return Flushed(AfterJobCond(met[0].step))
    return _own(condition, completed)
