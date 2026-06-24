"""Run an EXEC PGM COBOL step against the red-dragon VM."""

from __future__ import annotations

from pathlib import Path

from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.real_file_provider import RealFileIOProvider
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.return_code_readback import read_return_code
from interpreter.constants import Language
from interpreter.run import run

from jackal.catalog import DatasetCatalog
from jackal.model import Step
from jackal.results import StepDisposition, StepResult

# DDs whose absence is expected in the emulated environment and should be skipped
# silently rather than raising an error.
#   STEPLIB / JOBLIB — load-library DDs: real mainframe load libraries are never
#   present in the local file tree; the emulator finds programs via source_dir instead.
OPTIONAL_DDS: frozenset[str] = frozenset({"STEPLIB", "JOBLIB"})


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
        if dd.ddname in OPTIONAL_DDS:
            continue
        overrides[dd.ddname] = catalog.allocate(dd).path
    return overrides


def run_cobol_step(
    step: Step,
    source: str,
    catalog: DatasetCatalog,
    bridge_jar: str,
    copybook_dirs: list[Path],
) -> StepResult:
    if not bridge_jar:
        raise ValueError(
            f"PROLEAP_BRIDGE_JAR not set; required to run COBOL step {step.name!r}"
        )
    overrides = _overrides(step, catalog)
    provider = RealFileIOProvider(
        base_dir=catalog.workdir,
        file_control=_file_control(source, bridge_jar, copybook_dirs),
        path_overrides=overrides,
    )
    vm = run(
        source,
        language=Language.COBOL,
        io_provider=provider,
        max_steps=500_000,
        copybook_dirs=copybook_dirs,
    )
    for dd in step.dds:
        catalog.dispose(dd)
    return StepResult(
        name=step.name,
        return_code=read_return_code(vm),
        ran=True,
        disposition=StepDisposition.EXECUTED,
    )
