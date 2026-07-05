"""Sequence a Job's steps, threading a job-scoped DatasetCatalog."""

from __future__ import annotations

from pathlib import Path

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.cond import should_bypass
from jackal.dsn import BackwardRef, DirectDSN, TempRef
from jackal.model import DD, Job, Step
from jackal.results import JobResult, StepDisposition, StepResult
from jackal.utilities import UTILITIES


class JobRunner:
    def __init__(
        self,
        source_dir: Path,
        bridge_jar: str,
        data_dir: Path,
        copybook_dir: Path,
    ):
        self._source_dir = source_dir
        self._bridge_jar = bridge_jar
        self._data_dir = data_dir
        self._copybook_dir = copybook_dir

    def run(self, job: Job, workdir: Path, seeds: dict[str, Path]) -> JobResult:
        catalog = DatasetCatalog(workdir=workdir, data_dir=self._data_dir)
        for dsn, path in seeds.items():
            catalog.seed(dsn, path)
        return self.run_job(job, catalog)

    def run_job(self, job: Job, catalog: DatasetCatalog) -> JobResult:
        """Run a job against a pre-built catalog, honoring COND= and backward refs."""
        executed: list[StepResult] = []
        results: list[StepResult] = []
        resolved_dds: dict[str, dict[str, DirectDSN]] = {}
        try:
            for step in job.steps:
                conds = job.cond + step.conds
                if should_bypass(conds, tuple(executed)):
                    results.append(
                        StepResult(
                            name=step.name,
                            return_code=0,
                            ran=False,
                            disposition=StepDisposition.BYPASSED,
                        )
                    )
                    continue
                resolved_step = self._resolve_step(step, resolved_dds)
                if resolved_step is None:
                    results.append(
                        StepResult(
                            name=step.name,
                            return_code=0,
                            ran=False,
                            disposition=StepDisposition.BYPASSED,
                        )
                    )
                    continue
                self._record_dds(step.name, resolved_step.dds, resolved_dds)
                result = self._run_step(resolved_step, catalog)
                executed.append(result)
                results.append(result)
        finally:
            catalog.cleanup_temps()
        return JobResult(steps=tuple(results))

    def _resolve_step(
        self,
        step: Step,
        resolved_dds: dict[str, dict[str, DirectDSN]],
    ) -> Step | None:
        """Substitute BackwardRefs with their resolved DirectDSN.

        Returns None if any referenced step is absent from resolved_dds
        (IBM behavior: bypass the referencing step when its predecessor didn't run).
        """
        new_dds: list[DD] = []
        for dd in step.dds:
            match dd.dsn:
                case BackwardRef(step=s, ddname=dn):
                    if s not in resolved_dds:
                        return None
                    if dn not in resolved_dds[s]:
                        raise KeyError(
                            f"BackwardRef '*.{s}.{dn}' in step '{step.name}': "
                            f"DD '{dn}' was not recorded for step '{s}'"
                        )
                    new_dds.append(
                        DD(
                            dd.ddname,
                            resolved_dds[s][dn],
                            dd.disp,
                            dd.in_stream,
                            dd.sysout,
                        )
                    )
                case _:
                    new_dds.append(dd)
        return Step(step.name, step.pgm, tuple(new_dds), step.conds, step.parm)

    def _record_dds(
        self,
        step_name: str,
        dds: tuple[DD, ...],
        resolved_dds: dict[str, dict[str, DirectDSN]],
    ) -> None:
        """Record each DD's resolved DirectDSN into the registry for future backward refs."""
        entry: dict[str, DirectDSN] = {}
        for dd in dds:
            match dd.dsn:
                case DirectDSN() as d:
                    entry[dd.ddname] = d
                case TempRef(alias=a):
                    entry[dd.ddname] = DirectDSN(a[2:])  # strip leading &&
        resolved_dds[step_name] = entry

    def _run_step(self, step: Step, catalog: DatasetCatalog) -> StepResult:
        if step.pgm in UTILITIES:
            return UTILITIES[step.pgm](step, catalog)
        source = (self._source_dir / f"{step.pgm}.cbl").read_text()
        return run_cobol_step(
            step,
            source,
            catalog,
            self._bridge_jar,
            [self._copybook_dir],
        )
