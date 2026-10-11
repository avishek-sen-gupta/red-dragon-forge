"""Run an ExpandedJob's steps in order, threading a job-scoped DatasetCatalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

from jackal.allocation import LOAD_LIBRARIES, DdEnvironment, allocate, dispose
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
    Job,
    ProgramStep,
    QualifiedStep,
    RcComparison,
    ResolvedDd,
    StepCondition,
    StepReference,
    UnexpandedCall,
)
from jackal.program_sources import CobolSource, DirectoryProgramSources, SourceNotFound
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


class UnsupportedStep(Exception):
    """A step jackal cannot run yet: a step under an IF, or a concatenated DD."""


@dataclass(frozen=True)
class _History:
    results: tuple[StepResult, ...]

    def recorded(self, entry: Entry, outcome: StepOutcome) -> _History:
        return _History((*self.results, StepResult(entry, outcome)))


def _copied(dsn: DSN[StepReference]) -> DSN[StepReference]:
    match dsn:
        case BackwardRef(dd=ResolvedDd(dd=referenced)):
            return _copied(referenced.dsn)
        case _:
            return dsn


def _resolved_dd(dd: DD[StepReference]) -> DD[StepReference]:
    return DD(
        dd.ddname,
        _copied(dd.dsn),
        dd.disp,
        dd.in_stream,
        dd.sysout,
        dd.concatenated,
    )


def _concatenated(
    qualified: QualifiedStep, step: ProgramStep[StepReference]
) -> ProgramStep[StepReference]:
    names = tuple(
        dd.ddname.text
        for dd in step.dds
        if dd.concatenated and dd.ddname not in LOAD_LIBRARIES
    )
    if names:
        raise UnsupportedStep(
            f"{qualified.rendered()} concatenates DD {names[0]}; concatenated "
            "reads are not supported yet (jackal-1o2.5)"
        )
    return step


def _unguarded(qualified: QualifiedStep) -> ProgramStep[StepReference]:
    if qualified.step.guard != Always():
        raise UnsupportedStep(
            f"{qualified.rendered()} is under an IF; IF/THEN/ELSE does not run yet "
            "(jackal-1o2.8)"
        )
    return _concatenated(qualified, qualified.step)


class JobRunner:
    def __init__(
        self,
        source_dir: Path,
        bridge_jar: str,
        data_dir: Path,
        copybook_dir: Path,
        unresolved: UnresolvedReferenceStrategy,
        missing_data: MissingDataStrategy,
        missing_program: MissingProgramStrategy,
        proclib_dirs: Sequence[Path] = (),
    ):
        self._sources = DirectoryProgramSources(source_dir)
        self._bridge_jar = bridge_jar
        self._data_dir = data_dir
        self._copybook_dir = copybook_dir
        self._unresolved = unresolved
        self._missing_data = missing_data
        self._missing_program = missing_program
        self._library = DirectoryProcLibrary(tuple(proclib_dirs))

    def run(self, job: Job, workdir: Path, seeds: Mapping[str, Path]) -> JobResult:
        catalog = DatasetCatalog(workdir=workdir, data_dir=self._data_dir)
        for dsn, path in seeds.items():
            catalog.seed(dsn, path)
        return self.run_job(job, catalog)

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
            catalog.cleanup_temps()
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
                decision = gate(_NO_CONDITION, end_job_tests, history.results)
                return history.recorded(entry, _unrunnable(decision))
            case QualifiedStep():
                step = _unguarded(entry)
                return self._gated(catalog, end_job_tests, history, entry, step)

    def _gated(
        self,
        catalog: DatasetCatalog,
        end_job_tests: Sequence[RcComparison],
        history: _History,
        qualified: QualifiedStep,
        step: ProgramStep[StepReference],
    ) -> _History:
        decision = gate(step.cond, end_job_tests, history.results)
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
            tuple(_resolved_dd(dd) for dd in step.dds),
            step.cond,
            step.parm,
            step.guard,
        )
        match allocate(qualified, resolved, catalog, self._missing_data):
            case AllocationFailed() as failure:
                return history.recorded(qualified, failure)
            case DdEnvironment() as env:
                result = self._run_program(qualified, resolved, env, catalog)
                dispose(resolved, env, catalog, result)
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
                return Completed(
                    run_cobol_step(
                        step,
                        source,
                        env,
                        catalog.workdir,
                        self._bridge_jar,
                        [self._copybook_dir],
                    )
                )
