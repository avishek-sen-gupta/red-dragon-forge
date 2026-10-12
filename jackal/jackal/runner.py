"""Run an ExpandedJob's steps in order, threading a job-scoped DatasetCatalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import reduce
from pathlib import Path

from interpreter.project.coprocessor_compile import CoprocessorSpec
from jackal.allocation import DdEnvironment, allocate, dispose, release
from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.cond import Run, gate
from jackal.expansion import DirectoryProcLibrary, expand_or_fail
from jackal.missing_data import MissingDataStrategy
from jackal.missing_program import MissingProgramStrategy
from jackal.model import (
    DD,
    DSN,
    AbendMode,
    Always,
    BackwardRef,
    Dcb,
    DdName,
    Job,
    ProgramRef,
    ProgramStep,
    QualifiedStep,
    RcComparison,
    ResolvedDd,
    StepCondition,
    StepDd,
    StepReference,
    UnexpandedCall,
)
from jackal.program_compiler import ProgramCompiler
from jackal.program_sources import (
    CobolSource,
    DirectoryProgramSources,
    LinkedProgramNotFound,
    ProgramSources,
    SourceNotFound,
)
from jackal.results import (
    AllocationFailed,
    Bypassed,
    Completed,
    Flushed,
    JobResult,
    ProgramResult,
    SkippedUnresolved,
    StepOutcome,
    StepResult,
)
from jackal.system_catalog import SystemCatalog
from jackal.tso_step import dsn_runs, run_tso_step
from jackal.unresolved import UnresolvedReferenceStrategy, referbacks_resolved
from jackal.utilities import UTILITIES

Entry = QualifiedStep | UnexpandedCall


_NO_CONDITION: StepCondition[StepReference] = StepCondition((), AbendMode.NORMAL)


def _unrunnable(decision: Run | Bypassed | Flushed) -> StepOutcome:
    match decision:
        case Run():
            return SkippedUnresolved()
        case _:
            return decision


@dataclass(frozen=True)
class _History:
    results: tuple[StepResult, ...]

    def recorded(self, entry: Entry, outcome: StepOutcome) -> _History:
        return _History((*self.results, StepResult(entry, outcome)))


def _copied(
    dsn: DSN[StepReference], earlier: Mapping[DdName, DSN[StepReference]]
) -> DSN[StepReference]:
    match dsn:
        case BackwardRef(dd=ResolvedDd(dd=referenced)):
            return _copied(referenced.dsn, {})
        case StepDd(ddname=name) if name in earlier:
            return earlier[name]
        case _:
            return dsn


def _dcb_copied(
    dcb: Dcb[StepReference], earlier: Mapping[DdName, DD[StepReference]]
) -> Dcb[StepReference]:
    match dcb.model:
        case BackwardRef(dd=ResolvedDd(dd=referenced)):
            return dcb.completed_by(referenced.dcb)
        case StepDd(ddname=name) if name in earlier:
            return dcb.completed_by(earlier[name].dcb)
        case _:
            return dcb


def _resolved_after(
    done: tuple[DD[StepReference], ...], dd: DD[StepReference]
) -> tuple[DD[StepReference], ...]:
    earlier = {d.ddname: d for d in done}
    dsns = {name: d.dsn for name, d in earlier.items()}
    return (
        *done,
        replace(dd, dsn=_copied(dd.dsn, dsns), dcb=_dcb_copied(dd.dcb, earlier)),
    )


def _resolved_dds(
    dds: tuple[DD[StepReference], ...],
) -> tuple[DD[StepReference], ...]:
    return reduce(_resolved_after, dds, ())


def _linked_source(sources: ProgramSources, pgm: ProgramRef) -> CobolSource:
    match sources.find(pgm):
        case CobolSource() as source:
            return source
        case SourceNotFound():
            raise LinkedProgramNotFound(pgm)


class JobRunner:
    def __init__(
        self,
        source_dir: Path,
        bridge_jar: str,
        system: SystemCatalog,
        copybook_dir: Path,
        unresolved: UnresolvedReferenceStrategy,
        missing_data: MissingDataStrategy,
        missing_program: MissingProgramStrategy,
        program_step_budget: int,
        proclib_dirs: Sequence[Path] = (),
        coprocessors: Sequence[CoprocessorSpec] = (),
        linked_programs: Sequence[ProgramRef] = (),
    ):
        self._sources = DirectoryProgramSources(source_dir)
        self._compiler = ProgramCompiler(
            bridge_jar,
            (copybook_dir,),
            (source_dir,),
            tuple(coprocessors),
            {pgm: _linked_source(self._sources, pgm) for pgm in linked_programs},
        )
        self._system = system
        self._unresolved = unresolved
        self._missing_data = missing_data
        self._missing_program = missing_program
        self._program_step_budget = program_step_budget
        self._library = DirectoryProcLibrary(tuple(proclib_dirs))

    def run(self, job: Job, scratch: Path) -> JobResult:
        return self.run_job(job, DatasetCatalog(scratch, self._system))

    def run_job(self, job: Job, catalog: DatasetCatalog) -> JobResult:
        expanded = self._unresolved.admit(expand_or_fail(job, self._library))
        try:
            history = reduce(
                lambda done, entry: self._next(
                    catalog, expanded.end_job_tests, done, entry
                ),
                expanded.steps,
                _History(()),
            )
        finally:
            catalog.end_job()
        return JobResult(history.results)

    def _next(
        self,
        catalog: DatasetCatalog,
        end_job_tests: Sequence[RcComparison],
        history: _History,
        entry: Entry,
    ) -> _History:
        match entry:
            case UnexpandedCall():
                decision = gate(_NO_CONDITION, Always(), end_job_tests, history.results)
                return history.recorded(entry, _unrunnable(decision))
            case QualifiedStep():
                return self._gated(catalog, end_job_tests, history, entry, entry.step)

    def _gated(
        self,
        catalog: DatasetCatalog,
        end_job_tests: Sequence[RcComparison],
        history: _History,
        qualified: QualifiedStep,
        step: ProgramStep[StepReference],
    ) -> _History:
        decision = gate(step.cond, step.guard, end_job_tests, history.results)
        match decision:
            case Run() if not referbacks_resolved(step):
                return history.recorded(qualified, SkippedUnresolved())
            case Run():
                return self._started(catalog, history, qualified, step)
            case _:
                return history.recorded(qualified, decision)

    def _started(
        self,
        catalog: DatasetCatalog,
        history: _History,
        qualified: QualifiedStep,
        step: ProgramStep[StepReference],
    ) -> _History:
        resolved = ProgramStep(
            step.label,
            step.pgm,
            tuple(map(catalog.generations_expanded, _resolved_dds(step.dds))),
            step.cond,
            step.parm,
            step.guard,
        )
        match allocate(qualified, resolved, catalog, self._missing_data):
            case AllocationFailed() as failure:
                return history.recorded(qualified, failure)
            case DdEnvironment() as env:
                try:
                    result = self._run_program(qualified, resolved, env, catalog)
                    dispose(resolved, env, catalog, result)
                finally:
                    release(resolved, env)
                return history.recorded(qualified, result)

    def _run_program(
        self,
        qualified: QualifiedStep,
        step: ProgramStep[StepReference],
        env: DdEnvironment,
        catalog: DatasetCatalog,
    ) -> ProgramResult:
        if step.pgm in UTILITIES:
            return Completed(UTILITIES[step.pgm](step, env, catalog))
        runs = dsn_runs(step)
        if runs:
            return run_tso_step(
                step,
                runs,
                lambda pgm: self._found(
                    qualified, replace(step, pgm=pgm), env, catalog
                ),
            )
        return self._found(qualified, step, env, catalog)

    def _found(
        self,
        qualified: QualifiedStep,
        step: ProgramStep[StepReference],
        env: DdEnvironment,
        catalog: DatasetCatalog,
    ) -> ProgramResult:
        match self._sources.find(step.pgm):
            case SourceNotFound():
                return self._missing_program.settle(qualified, step.pgm)
            case CobolSource(text=source):
                return run_cobol_step(
                    step,
                    self._compiler.compiled(source),
                    env,
                    catalog.workdir,
                    self._program_step_budget,
                    catalog,
                )
