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
    ResolvedProcCall,
    StepRef,
    StepReference,
    UnexpandedCall,
)

AnyDD: TypeAlias = DD[StepRef] | DD[StepReference]


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


def _outermost(coordinates: tuple[ResolvedProcCall, ...]) -> tuple[ProcRef, ...]:
    return tuple(c.call.proc for c in coordinates[:1])


def _expanded_view(entry: QualifiedStep | UnexpandedCall) -> StepView:
    match entry:
        case UnexpandedCall():
            return _call_view(
                entry.rendered(), _outermost(entry.coordinates[:-1]), entry.call()
            )
        case QualifiedStep(coordinates=coordinates, step=step):
            return StepView(
                entry.rendered(),
                step.pgm.name,
                _outermost(coordinates),
                _own_dds(step.dds),
            )


def expanded_steps(job: ExpandedJob) -> tuple[StepView, ...]:
    return tuple(_expanded_view(entry) for entry in job.steps)


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
