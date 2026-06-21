"""Emulated utility programs (no COBOL load module)."""

from __future__ import annotations

from collections.abc import Callable

from jackal.catalog import DatasetCatalog
from jackal.idcams.executor import run_idcams
from jackal.idcams.parser import parse_idcams
from jackal.model import Step
from jackal.results import StepResult


def iefbr14(step: Step, catalog: DatasetCatalog) -> StepResult:
    """No-op program: its only effect is the DD allocate/dispose lifecycle."""
    for dd in step.dds:
        catalog.allocate(dd)
    for dd in step.dds:
        catalog.dispose(dd)
    return StepResult(name=step.name, return_code=0, ran=True)


def idcams(step: Step, catalog: DatasetCatalog) -> StepResult:
    """IDCAMS utility: parse SYSIN in-stream and execute IDCAMS commands."""
    sysin = next(d for d in step.dds if d.ddname == "SYSIN")
    commands = parse_idcams("\n".join(sysin.in_stream) + "\n")
    rc = run_idcams(commands, step.dds, catalog)
    return StepResult(name=step.name, return_code=rc, ran=True)


UTILITIES: dict[str, Callable[[Step, DatasetCatalog], StepResult]] = {
    "IEFBR14": iefbr14,
    "IDCAMS": idcams,
}
