"""Sequence a Job's steps, threading a job-scoped DatasetCatalog."""

from __future__ import annotations

from pathlib import Path

from jackal.catalog import DatasetCatalog
from jackal.cobol_step import run_cobol_step
from jackal.model import Job, Step
from jackal.results import JobResult, StepResult
from jackal.utilities import UTILITIES


class JobRunner:
    def __init__(self, source_dir: Path, bridge_jar: str):
        self._source_dir = source_dir
        self._bridge_jar = bridge_jar

    def run(self, job: Job, workdir: Path, seeds: dict[str, Path]) -> JobResult:
        catalog = DatasetCatalog(workdir=workdir)
        for dsn, path in seeds.items():
            catalog.seed(dsn, path)
        return JobResult(steps=tuple(self._run_step(s, catalog) for s in job.steps))

    def _run_step(self, step: Step, catalog: DatasetCatalog) -> StepResult:
        if step.pgm in UTILITIES:
            return UTILITIES[step.pgm](step, catalog)
        source = (self._source_dir / f"{step.pgm}.cbl").read_text()
        return run_cobol_step(step, source, catalog, self._bridge_jar)
