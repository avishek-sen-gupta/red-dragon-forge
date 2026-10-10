"""Run an ExpandedJob's steps in order, threading a job-scoped DatasetCatalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import OPTIONAL_DDS, run_cobol_step
from jackal.cond import Run, gate
from jackal.expansion import DirectoryProcLibrary, expand_or_fail
from jackal.model import (
    DD,
    DSN,
    Always,
    BackwardRef,
    DdName,
    DirectDSN,
    Job,
    ProgramStep,
    QualifiedStep,
    RcComparison,
    StepReference,
    TempRef,
    UnexpandedCall,
)
from jackal.results import (
    Bypassed,
    BypassReason,
    Completed,
    JobResult,
    SkippedUnresolved,
    StepOutcome,
    StepResult,
)
from jackal.unresolved import UnresolvedReferenceStrategy, referbacks_resolved
from jackal.utilities import UTILITIES
from jackal.value_parts import literal

Recorded = Mapping[DdName, DSN[StepReference]]
Entry = QualifiedStep | UnexpandedCall
_REFERENCED_STEP_NOT_RUN = Bypassed(BypassReason.REFERENCED_STEP_NOT_RUN)


class UnsupportedStep(Exception):
    """A step jackal cannot run yet: a step under an IF, or a concatenated DD."""


@dataclass(frozen=True)
class _History:
    results: tuple[StepResult, ...]
    datasets: Mapping[StepReference, Recorded]

    def recorded(self, entry: Entry, outcome: StepOutcome) -> _History:
        return _History((*self.results, StepResult(entry, outcome)), self.datasets)

    def ran(self, step: QualifiedStep, rc: int, recorded: Recorded) -> _History:
        result = StepResult(step, Completed(rc))
        datasets = {**self.datasets, step.reference(): recorded}
        return _History((*self.results, result), datasets)


def _recorded_dsn(dsn: DSN[StepReference]) -> DSN[StepReference]:
    match dsn:
        case TempRef(name=name):
            return DirectDSN(literal(name))
        case _:
            return dsn


def _recorded(step: ProgramStep[StepReference]) -> Recorded:
    return {dd.ddname: _recorded_dsn(dd.dsn) for dd in step.dds}


def _referenced(step: ProgramStep[StepReference]) -> tuple[StepReference, ...]:
    return tuple(dd.dsn.step for dd in step.dds if isinstance(dd.dsn, BackwardRef))


def _resolved_dsn(
    dsn: DSN[StepReference], datasets: Mapping[StepReference, Recorded]
) -> DSN[StepReference]:
    match dsn:
        case BackwardRef(step=step, dd=dd):
            return datasets[step][dd.ddname()]
        case _:
            return dsn


def _resolved_dd(
    dd: DD[StepReference], datasets: Mapping[StepReference, Recorded]
) -> DD[StepReference]:
    return DD(
        dd.ddname,
        _resolved_dsn(dd.dsn, datasets),
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
        if dd.concatenated and dd.ddname not in OPTIONAL_DDS
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
        proclib_dirs: Sequence[Path] = (),
    ):
        self._source_dir = source_dir
        self._bridge_jar = bridge_jar
        self._data_dir = data_dir
        self._copybook_dir = copybook_dir
        self._unresolved = unresolved
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
                _History((), {}),
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
                return history.recorded(entry, SkippedUnresolved())
            case QualifiedStep():
                return self._step(catalog, end_job_tests, history, entry)

    def _step(
        self,
        catalog: DatasetCatalog,
        end_job_tests: Sequence[RcComparison],
        history: _History,
        qualified: QualifiedStep,
    ) -> _History:
        step = _unguarded(qualified)
        if not referbacks_resolved(step):
            return history.recorded(qualified, SkippedUnresolved())
        return self._gated(catalog, end_job_tests, history, qualified, step)

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
        if any(s not in history.datasets for s in _referenced(step)):
            return history.recorded(qualified, _REFERENCED_STEP_NOT_RUN)
        resolved = ProgramStep(
            step.label,
            step.pgm,
            tuple(_resolved_dd(dd, history.datasets) for dd in step.dds),
            step.cond,
            step.parm,
            step.guard,
        )
        rc = self._run_program(resolved, catalog)
        return history.ran(qualified, rc, _recorded(resolved))

    def _run_program(
        self, step: ProgramStep[StepReference], catalog: DatasetCatalog
    ) -> int:
        if step.pgm in UTILITIES:
            return UTILITIES[step.pgm](step, catalog)
        source = (self._source_dir / f"{step.pgm.name}.cbl").read_text()
        return run_cobol_step(
            step, source, catalog, self._bridge_jar, [self._copybook_dir]
        )
