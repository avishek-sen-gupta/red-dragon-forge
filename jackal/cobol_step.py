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


def _file_control(source: str, bridge_jar: str, copybook_dirs: list[Path]) -> list:
    parser = ProLeapCobolParser(
        runner=RealSubprocessRunner(),
        bridge_jar=bridge_jar,
        copybook_dirs=copybook_dirs,
    )
    return parser.parse(source.encode("utf-8")).file_control


def _overrides(step: Step, catalog: DatasetCatalog) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for dd in step.dds:
        if dd.sysout:
            continue
        try:
            overrides[dd.ddname] = catalog.allocate(dd).path
        except KeyError:
            # Dataset not in catalog and not on disk: skip (e.g. STEPLIB load lib
            # that does not exist in the emulated environment).
            pass
    return overrides


def run_cobol_step(
    step: Step,
    source: str,
    catalog: DatasetCatalog,
    bridge_jar: str,
    copybook_dirs: list[Path],
) -> StepResult:
    overrides = _overrides(step, catalog)
    provider = RealFileIOProvider(
        base_dir=catalog.workdir,
        file_control=_file_control(source, bridge_jar, copybook_dirs),
        path_overrides=overrides,
    )
    run(
        source,
        language=Language.COBOL,
        io_provider=provider,
        max_steps=500_000,
        copybook_dirs=copybook_dirs,
    )
    for dd in step.dds:
        catalog.dispose(dd)
    return StepResult(name=step.name, return_code=0, ran=True)
