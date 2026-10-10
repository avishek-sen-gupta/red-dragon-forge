"""Run an ExpandedJob's steps in order, threading a job-scoped DatasetCatalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import OPTIONAL_DDS, run_cobol_step
from jackal.cond import should_bypass
from jackal.expansion import DirectoryProcLibrary, expand_or_fail
from jackal.model import (
    DD,
    DSN,
    AllPriorSteps,
    Always,
    BackwardRef,
    BypassTest,
    DdName,
    DirectDSN,
    Job,
    ProgramStep,
    QualifiedStep,
    RcComparison,
    ResolvedDd,
    ResolvedProgramStep,
    StepReference,
    TempRef,
    UnexpandedCall,
)
from jackal.results import JobResult, StepDisposition, StepResult
from jackal.utilities import UTILITIES
from jackal.value_parts import literal

Recorded = Mapping[DdName, DSN[StepReference]]
Entry = QualifiedStep | UnexpandedCall


class UnsupportedStep(Exception):
    """A step jackal cannot run yet: an unexpanded PROC call, a guard, a concatenation, an unresolved reference."""


@dataclass(frozen=True)
class _History:
    results: tuple[StepResult, ...]
    datasets: Mapping[StepReference, Recorded]

    def bypassed(self, step: QualifiedStep) -> _History:
        result = StepResult(step, 0, StepDisposition.BYPASSED)
        return _History((*self.results, result), self.datasets)

    def ran(self, step: QualifiedStep, rc: int, recorded: Recorded) -> _History:
        result = StepResult(step, rc)
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


def _fully_resolved(reference: StepReference) -> bool:
    return isinstance(reference.target, ResolvedProgramStep)


def _test_resolved(test: BypassTest[StepReference]) -> bool:
    match test.target:
        case AllPriorSteps():
            return True
        case _:
            return _fully_resolved(test.target)


def _referback_resolved(dd: DD[StepReference]) -> bool:
    match dd.dsn:
        case BackwardRef(dd=coordinate):
            return isinstance(coordinate, ResolvedDd)
        case _:
            return True


def _unresolved(
    qualified: QualifiedStep, step: ProgramStep[StepReference]
) -> ProgramStep[StepReference]:
    tests = all(_test_resolved(t) for t in step.cond.bypass_tests)
    referbacks = all(_referback_resolved(dd) for dd in step.dds)
    if not (tests and referbacks):
        raise UnsupportedStep(
            f"{qualified.rendered()} refers to a step or DD that is not resolved; "
            "running such a step is undecided (blueprint D7)"
        )
    return step


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
    return _unresolved(qualified, step)


def _unguarded(qualified: QualifiedStep) -> ProgramStep[StepReference]:
    if qualified.step.guard != Always():
        raise UnsupportedStep(
            f"{qualified.rendered()} is under an IF; IF/THEN/ELSE does not run yet "
            "(jackal-1o2.8)"
        )
    return _concatenated(qualified, qualified.step)


def _runnable(entry: Entry) -> QualifiedStep:
    match entry:
        case UnexpandedCall():
            raise UnsupportedStep(
                f"{entry.rendered()}: PROC {entry.call().proc.name} is in no proclib"
            )
        case QualifiedStep():
            return entry


class JobRunner:
    def __init__(
        self,
        source_dir: Path,
        bridge_jar: str,
        data_dir: Path,
        copybook_dir: Path,
        proclib_dirs: Sequence[Path] = (),
    ):
        self._source_dir = source_dir
        self._bridge_jar = bridge_jar
        self._data_dir = data_dir
        self._copybook_dir = copybook_dir
        self._library = DirectoryProcLibrary(tuple(proclib_dirs))

    def run(self, job: Job, workdir: Path, seeds: Mapping[str, Path]) -> JobResult:
        catalog = DatasetCatalog(workdir=workdir, data_dir=self._data_dir)
        for dsn, path in seeds.items():
            catalog.seed(dsn, path)
        return self.run_job(job, catalog)

    def run_job(self, job: Job, catalog: DatasetCatalog) -> JobResult:
        expanded = expand_or_fail(job, self._library)
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
        qualified = _runnable(entry)
        step = _unguarded(qualified)
        if should_bypass(step.cond, end_job_tests, history.results):
            return history.bypassed(qualified)
        if any(s not in history.datasets for s in _referenced(step)):
            return history.bypassed(qualified)
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
