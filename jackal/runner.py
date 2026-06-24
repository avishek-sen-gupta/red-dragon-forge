"""Sequence a Job's steps, threading a job-scoped DatasetCatalog."""

from __future__ import annotations

from pathlib import Path

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.cond import should_bypass
from jackal.model import Job, Step
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
        """Run a job against a pre-built catalog, honoring COND= step bypass.

        Threads the results of steps that actually executed; before each step,
        bypass it if job-level or step-level COND= is satisfied (IBM semantics:
        bypass if any condition is true against any prior executed step).
        """
        executed: list[StepResult] = []
        results: list[StepResult] = []
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
            result = self._run_step(step, catalog)
            executed.append(result)
            results.append(result)
        return JobResult(steps=tuple(results))

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
