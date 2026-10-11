"""Pure evaluation of JCL COND= step-bypass conditions (IBM semantics)."""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from jackal.if_guard import holds, tests_abend
from jackal.model import (
    AbendMode,
    AllPriorSteps,
    BypassTest,
    CondOp,
    Guard,
    QualifiedStep,
    RcComparison,
    StepCondition,
    StepReference,
    UnexpandedCall,
)
from jackal.results import (
    Abended,
    AfterAbend,
    AfterAllocationFailure,
    AfterJobCond,
    AllocationFailed,
    Bypassed,
    BypassReason,
    Flushed,
    StepResult,
)

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
class _Gated:
    condition: StepCondition[StepReference]
    guard: Guard[StepReference]


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


def _guarded(
    step: _Gated, history: Sequence[StepResult], completed: Sequence[_Completed]
) -> Run | Bypassed:
    if not holds(step.guard, history):
        return Bypassed(BypassReason.IF_CONDITION_FALSE)
    return _own(step.condition, completed)


def _own(
    condition: StepCondition[StepReference], completed: Sequence[_Completed]
) -> Run | Bypassed:
    if any(_true(t, completed) for t in condition.bypass_tests):
        return Bypassed(BypassReason.COND_SATISFIED)
    return Run()


def _abended(result: StepResult) -> tuple[QualifiedStep, ...]:
    match (result.step, result.outcome):
        case (QualifiedStep(), Abended()):
            return (result.step,)
        case _:
            return ()


def _after_abend(
    step: _Gated,
    history: Sequence[StepResult],
    completed: Sequence[_Completed],
) -> Run | Bypassed | Flushed:
    abended = tuple(s for r in history for s in _abended(r))
    if not abended:
        return _without_abend(step, history, completed)
    if step.condition.abend_mode is AbendMode.NORMAL and not tests_abend(step.guard):
        return Flushed(AfterAbend(abended[0]))
    return _guarded(step, history, completed)


def _without_abend(
    step: _Gated, history: Sequence[StepResult], completed: Sequence[_Completed]
) -> Run | Bypassed:
    if step.condition.abend_mode is AbendMode.ONLY:
        return Bypassed(BypassReason.ONLY_WITHOUT_ABEND)
    return _guarded(step, history, completed)


def _allocation_failed(result: StepResult) -> tuple[QualifiedStep, ...]:
    match (result.step, result.outcome):
        case (QualifiedStep(), AllocationFailed()):
            return (result.step,)
        case _:
            return ()


def _after_job_cond(
    step: _Gated,
    end_job_tests: Sequence[RcComparison],
    history: Sequence[StepResult],
) -> Run | Bypassed | Flushed:
    completed = tuple(c for r in history for c in _completions(r))
    met = tuple(c for c in completed if _meets(end_job_tests, c))
    if met:
        return Flushed(AfterJobCond(met[0].step))
    return _after_abend(step, history, completed)


def gate(
    condition: StepCondition[StepReference],
    guard: Guard[StepReference],
    end_job_tests: Sequence[RcComparison],
    history: Sequence[StepResult],
) -> Run | Bypassed | Flushed:
    failed = tuple(s for r in history for s in _allocation_failed(r))
    if failed:
        return Flushed(AfterAllocationFailure(failed[0]))
    return _after_job_cond(_Gated(condition, guard), end_job_tests, history)
