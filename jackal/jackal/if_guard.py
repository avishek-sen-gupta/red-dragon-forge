"""Pure evaluation of a step's JCL IF/THEN/ELSE condition against the steps before it (IBM semantics)."""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from jackal.model import (
    AbendCodeTest,
    AbendTest,
    AllOf,
    AllPriorSteps,
    AnyOf,
    CondOp,
    Guard,
    Negated,
    QualifiedStep,
    RcTest,
    RunTest,
    StepReference,
    SystemAbend,
    UserAbend,
)
from jackal.results import Abended, Completed, StepResult

_OPS: Mapping[CondOp, Callable[[int, int], bool]] = {
    CondOp.GT: operator.gt,
    CondOp.GE: operator.ge,
    CondOp.EQ: operator.eq,
    CondOp.NE: operator.ne,
    CondOp.LT: operator.lt,
    CondOp.LE: operator.le,
}


class _Truth(Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    NOT_STARTED = "NOT_STARTED"


@dataclass(frozen=True)
class _Ran:
    step: QualifiedStep
    outcome: Completed | Abended


def _truth(value: bool) -> _Truth:
    return _Truth.TRUE if value else _Truth.FALSE


def _ran(result: StepResult) -> tuple[_Ran, ...]:
    match (result.step, result.outcome):
        case (QualifiedStep(), Completed() | Abended()):
            return (_Ran(result.step, result.outcome),)
        case _:
            return ()


def _started(target: StepReference, ran: Sequence[_Ran]) -> tuple[_Ran, ...]:
    return tuple(r for r in ran if r.step.reference() == target)[:1]


def _rc(test: RcTest[StepReference], ran: Sequence[_Ran]) -> _Truth:
    match test.target:
        case AllPriorSteps():
            highest = max(
                (r.outcome.rc for r in ran if isinstance(r.outcome, Completed)),
                default=0,
            )
            return _truth(_OPS[test.op](highest, test.code))
        case _:
            return _step_rc(test, _started(test.target, ran))


def _step_rc(test: RcTest[StepReference], step: Sequence[_Ran]) -> _Truth:
    if not step:
        return _Truth.NOT_STARTED
    return _truth(any(_OPS[test.op](rc, test.code) for rc in step[0].outcome.rcs()))


def _abend(target: AllPriorSteps | StepReference, ran: Sequence[_Ran]) -> _Truth:
    match target:
        case AllPriorSteps():
            return _truth(any(isinstance(r.outcome, Abended) for r in ran))
        case _:
            return _step_abend(_started(target, ran))


def _step_abend(step: Sequence[_Ran]) -> _Truth:
    if not step:
        return _Truth.NOT_STARTED
    return _truth(isinstance(step[0].outcome, Abended))


def _same_code(outcome: Completed | Abended, code: SystemAbend | UserAbend) -> bool:
    match outcome:
        case Abended():
            return outcome.code == code
        case Completed():
            return False


def _abend_code(test: AbendCodeTest[StepReference], ran: Sequence[_Ran]) -> _Truth:
    match test.target:
        case AllPriorSteps():
            abends = tuple(r for r in ran if isinstance(r.outcome, Abended))
            return _truth(bool(abends) and _same_code(abends[-1].outcome, test.code))
        case _:
            return _step_abend_code(test, _started(test.target, ran))


def _step_abend_code(
    test: AbendCodeTest[StepReference], step: Sequence[_Ran]
) -> _Truth:
    if not step:
        return _Truth.NOT_STARTED
    return _truth(_same_code(step[0].outcome, test.code))


_NEGATED: Mapping[_Truth, _Truth] = {
    _Truth.TRUE: _Truth.FALSE,
    _Truth.FALSE: _Truth.TRUE,
    _Truth.NOT_STARTED: _Truth.NOT_STARTED,
}


def _all(guards: Sequence[Guard[StepReference]], ran: Sequence[_Ran]) -> _Truth:
    return _truth(all(_evaluated(g, ran) is _Truth.TRUE for g in guards))


def _any(guards: Sequence[Guard[StepReference]], ran: Sequence[_Ran]) -> _Truth:
    return _truth(any(_evaluated(g, ran) is _Truth.TRUE for g in guards))


def _evaluated(guard: Guard[StepReference], ran: Sequence[_Ran]) -> _Truth:
    match guard:
        case RcTest() | AbendTest() | AbendCodeTest() | RunTest():
            return _leaf(guard, ran)
        case _:
            return _composite(guard, ran)


def _leaf(
    guard: (
        RcTest[StepReference]
        | AbendTest[StepReference]
        | AbendCodeTest[StepReference]
        | RunTest[StepReference]
    ),
    ran: Sequence[_Ran],
) -> _Truth:
    match guard:
        case RcTest():
            return _rc(guard, ran)
        case AbendTest():
            return _abend(guard.target, ran)
        case _:
            return _code_or_run(guard, ran)


def _code_or_run(
    guard: AbendCodeTest[StepReference] | RunTest[StepReference],
    ran: Sequence[_Ran],
) -> _Truth:
    match guard:
        case AbendCodeTest():
            return _abend_code(guard, ran)
        case RunTest():
            return _truth(bool(_started(guard.step, ran)))


def _composite(
    guard: Guard[StepReference],
    ran: Sequence[_Ran],
) -> _Truth:
    match guard:
        case Negated():
            return _NEGATED[_evaluated(guard.guard, ran)]
        case _:
            return _joined(guard, ran)


def _joined(guard: Guard[StepReference], ran: Sequence[_Ran]) -> _Truth:
    match guard:
        case AllOf():
            return _all(guard.guards, ran)
        case AnyOf():
            return _any(guard.guards, ran)
        case _:
            return _Truth.TRUE


def holds(guard: Guard[StepReference], history: Sequence[StepResult]) -> bool:
    ran = tuple(r for result in history for r in _ran(result))
    return _evaluated(guard, ran) is _Truth.TRUE


def tests_abend(guard: Guard[StepReference]) -> bool:
    match guard:
        case AbendTest() | AbendCodeTest():
            return True
        case _:
            return any(tests_abend(g) for g in _operands(guard))


def _operands(guard: Guard[StepReference]) -> tuple[Guard[StepReference], ...]:
    match guard:
        case Negated():
            return (guard.guard,)
        case AllOf() | AnyOf():
            return guard.guards
        case _:
            return ()
