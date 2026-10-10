"""A job's steps as cobble draws them: rendered name, program, the PROCs it came through, and its DDs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import chain
from typing import TypeAlias

from jackal.expansion import ExpandedJob
from jackal.model import (
    DD,
    IfBlock,
    Job,
    JobStatement,
    ProcCall,
    ProcRef,
    ProgramStep,
    QualifiedStep,
    StepRef,
    UnresolvedProcCall,
)

AnyDD: TypeAlias = DD[StepRef] | DD[QualifiedStep]


@dataclass(frozen=True)
class NamedDd:
    rendered_name: str
    dd: AnyDD


@dataclass(frozen=True)
class StepView:
    rendered_name: str
    program: str
    procs: tuple[ProcRef, ...]
    dds: tuple[NamedDd, ...]


def _own_dds(dds: Sequence[AnyDD]) -> tuple[NamedDd, ...]:
    return tuple(NamedDd(dd.ddname.text, dd) for dd in dds)


def override_dds(call: ProcCall) -> tuple[NamedDd, ...]:
    qualified = (
        NamedDd(f"{procstep.text}.{dd.ddname.text}", dd)
        for procstep, overrides in call.per_step
        for dd in overrides.dds
    )
    return (*_own_dds(call.dds_for_first_step), *qualified)


def _call_view(name: str, procs: tuple[ProcRef, ...], call: ProcCall) -> StepView:
    return StepView(name, call.proc.name, procs, override_dds(call))


def _expanded_view(qualified: QualifiedStep) -> StepView:
    procs = tuple(c.proc for c in qualified.calls[:1])
    match qualified.step:
        case UnresolvedProcCall(call=call):
            return _call_view(qualified.rendered(), procs, call)
        case _:
            step = qualified.step
            return StepView(
                qualified.rendered(), step.pgm.name, procs, _own_dds(step.dds)
            )


def expanded_steps(job: ExpandedJob) -> tuple[StepView, ...]:
    return tuple(_expanded_view(q) for q in job.steps)


def _written(statement: JobStatement) -> tuple[ProgramStep[StepRef] | ProcCall, ...]:
    match statement:
        case IfBlock(then=then, otherwise=otherwise):
            return tuple(chain.from_iterable(_written(s) for s in (*then, *otherwise)))
        case _:
            return (statement,)


def _written_view(statement: ProgramStep[StepRef] | ProcCall) -> StepView:
    match statement:
        case ProcCall():
            return _call_view(statement.label.rendered(), (), statement)
        case _:
            return StepView(
                statement.label.rendered(),
                statement.pgm.name,
                (),
                _own_dds(statement.dds),
            )


def written_steps(job: Job) -> tuple[StepView, ...]:
    return tuple(
        _written_view(s) for s in chain.from_iterable(_written(s) for s in job.steps)
    )
