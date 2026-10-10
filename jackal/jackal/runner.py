"""Run an ExpandedJob's steps in order, threading a job-scoped DatasetCatalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import OPTIONAL_DDS, run_cobol_step
from jackal.cond import should_bypass
from jackal.dsn import DSN, BackwardRef, DdName, DirectDSN, TempRef
from jackal.expansion import DirectoryProcLibrary, expand_or_fail
from jackal.model import (
    DD,
    Always,
    Job,
    ProgramStep,
    QualifiedStep,
    RcComparison,
    UnresolvedProcCall,
)
from jackal.results import JobResult, StepDisposition, StepResult
from jackal.utilities import UTILITIES
from jackal.value_parts import literal

Recorded = Mapping[DdName, DSN[QualifiedStep]]


class UnsupportedStep(Exception):
    """A step jackal cannot run yet: an unresolved PROC call, a guard, a concatenation."""


@dataclass(frozen=True)
class _History:
    results: tuple[StepResult, ...]
    datasets: Mapping[QualifiedStep, Recorded]

    def bypassed(self, step: QualifiedStep) -> _History:
        result = StepResult(step, 0, StepDisposition.BYPASSED)
        return _History((*self.results, result), self.datasets)

    def ran(self, step: QualifiedStep, rc: int, recorded: Recorded) -> _History:
        result = StepResult(step, rc)
        return _History((*self.results, result), {**self.datasets, step: recorded})


def _recorded_dsn(dsn: DSN[QualifiedStep]) -> DSN[QualifiedStep]:
    match dsn:
        case TempRef(name=name):
            return DirectDSN(literal(name))
        case _:
            return dsn


def _recorded(step: ProgramStep[QualifiedStep]) -> Recorded:
    return {dd.ddname: _recorded_dsn(dd.dsn) for dd in step.dds}


def _referenced(step: ProgramStep[QualifiedStep]) -> tuple[QualifiedStep, ...]:
    return tuple(dd.dsn.step for dd in step.dds if isinstance(dd.dsn, BackwardRef))


def _resolved_dsn(
    dsn: DSN[QualifiedStep], datasets: Mapping[QualifiedStep, Recorded]
) -> DSN[QualifiedStep]:
    match dsn:
        case BackwardRef(step=step, ddname=ddname):
            return datasets[step][ddname]
        case _:
            return dsn


def _resolved_dd(
    dd: DD[QualifiedStep], datasets: Mapping[QualifiedStep, Recorded]
) -> DD[QualifiedStep]:
    return DD(
        dd.ddname,
        _resolved_dsn(dd.dsn, datasets),
        dd.disp,
        dd.in_stream,
        dd.sysout,
        dd.concatenated,
    )


def _runnable(qualified: QualifiedStep) -> ProgramStep[QualifiedStep]:
    match qualified.step:
        case UnresolvedProcCall(call=call):
            raise UnsupportedStep(
                f"{qualified.rendered()}: PROC {call.proc.name} is in no proclib"
            )
        case _:
            return _unguarded(qualified, qualified.step)


def _concatenated(
    qualified: QualifiedStep, step: ProgramStep[QualifiedStep]
) -> ProgramStep[QualifiedStep]:
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


def _unguarded(
    qualified: QualifiedStep, step: ProgramStep[QualifiedStep]
) -> ProgramStep[QualifiedStep]:
    if step.guard != Always():
        raise UnsupportedStep(
            f"{qualified.rendered()} is under an IF; IF/THEN/ELSE does not run yet "
            "(jackal-1o2.8)"
        )
    return _concatenated(qualified, step)


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
                lambda done, step: self._next(
                    catalog, expanded.end_job_tests, done, step
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
        qualified: QualifiedStep,
    ) -> _History:
        step = _runnable(qualified)
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
        self, step: ProgramStep[QualifiedStep], catalog: DatasetCatalog
    ) -> int:
        if step.pgm in UTILITIES:
            return UTILITIES[step.pgm](step, catalog)
        source = (self._source_dir / f"{step.pgm.name}.cbl").read_text()
        return run_cobol_step(
            step, source, catalog, self._bridge_jar, [self._copybook_dir]
        )
