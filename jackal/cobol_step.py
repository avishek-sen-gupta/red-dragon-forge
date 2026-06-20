"""Run an EXEC PGM COBOL step against the red-dragon VM."""

from __future__ import annotations

from pathlib import Path

from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.real_file_provider import RealFileIOProvider
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.constants import Language
from interpreter.run import run

from jackal.catalog import DatasetCatalog
from jackal.model import Step
from jackal.results import StepResult


def _file_control(source: str, bridge_jar: str) -> list:
    parser = ProLeapCobolParser(runner=RealSubprocessRunner(), bridge_jar=bridge_jar)
    return parser.parse(source.encode("utf-8")).file_control


def _overrides(step: Step, catalog: DatasetCatalog) -> dict[str, Path]:
    return {dd.ddname: catalog.allocate(dd).path for dd in step.dds}


def run_cobol_step(
    step: Step, source: str, catalog: DatasetCatalog, bridge_jar: str
) -> StepResult:
    overrides = _overrides(step, catalog)
    provider = RealFileIOProvider(
        base_dir=catalog.workdir,
        file_control=_file_control(source, bridge_jar),
        path_overrides=overrides,
    )
    run(source, language=Language.COBOL, io_provider=provider, max_steps=500_000)
    for dd in step.dds:
        catalog.dispose(dd)
    return StepResult(name=step.name, return_code=0, ran=True)
