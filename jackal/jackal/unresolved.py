"""What the runner does with an expanded job that holds unresolved references (blueprint D7)."""

from __future__ import annotations

from typing import Protocol

from jackal.expansion import ExpandedJob
from jackal.model import (
    DD,
    AllPriorSteps,
    BackwardRef,
    BypassTest,
    DdName,
    ProgramStep,
    QualifiedStep,
    ResolvedDd,
    ResolvedProgramStep,
    StepDd,
    StepReference,
    UnexpandedCall,
)


class UnresolvedReference(Exception):
    """An expanded job refers to a PROC, step or DD that is not resolved; z/OS rejects such a job."""


def _test_resolved(test: BypassTest[StepReference]) -> bool:
    match test.target:
        case AllPriorSteps():
            return True
        case _:
            return isinstance(test.target.target, ResolvedProgramStep)


def _referback_resolved(dd: DD[StepReference]) -> bool:
    match dd.dsn:
        case BackwardRef(dd=coordinate):
            return isinstance(coordinate, ResolvedDd)
        case _:
            return True


def _same_step_resolved(dd: DD[StepReference], earlier: frozenset[DdName]) -> bool:
    match dd.dsn:
        case StepDd(ddname=name):
            return name in earlier
        case _:
            return True


def referbacks_resolved(step: ProgramStep[StepReference]) -> bool:
    names = tuple(dd.ddname for dd in step.dds)
    return all(
        _referback_resolved(dd) and _same_step_resolved(dd, frozenset(names[:at]))
        for at, dd in enumerate(step.dds)
    )


def _step_unresolved(qualified: QualifiedStep) -> tuple[str, ...]:
    step = qualified.step
    tests = all(_test_resolved(t) for t in step.cond.bypass_tests)
    if tests and referbacks_resolved(step):
        return ()
    return (
        f"{qualified.rendered()} refers to a step or DD that is not resolved "
        "(blueprint D7)",
    )


def _unresolved(entry: QualifiedStep | UnexpandedCall) -> tuple[str, ...]:
    match entry:
        case UnexpandedCall():
            return (
                f"{entry.rendered()}: PROC {entry.call().proc.name} is in no proclib "
                "(blueprint D7)",
            )
        case QualifiedStep():
            return _step_unresolved(entry)


class UnresolvedReferenceStrategy(Protocol):
    def admit(self, job: ExpandedJob) -> ExpandedJob: ...


class RaiseErrorStrategy(UnresolvedReferenceStrategy):
    """Rejects the job before any step runs, as z/OS does at conversion."""

    def admit(self, job: ExpandedJob) -> ExpandedJob:
        sites = tuple(site for entry in job.steps for site in _unresolved(entry))
        if sites:
            raise UnresolvedReference(sites[0])
        return job


class IgnoreStrategy(UnresolvedReferenceStrategy):
    """Admits the job; the runner drops unresolved tests and skips what cannot run."""

    def admit(self, job: ExpandedJob) -> ExpandedJob:
        return job
