"""Emulated utility programs (no COBOL load module)."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from jackal.allocation import DdEnvironment
from jackal.catalog import DatasetCatalog
from jackal.idcams.executor import run_idcams
from jackal.idcams.parser import parse_idcams
from jackal.model import DdName, ProgramRef, ProgramStep, StepReference

Utility = Callable[[ProgramStep[StepReference], DdEnvironment, DatasetCatalog], int]

_SYSIN = DdName("SYSIN")


def iefbr14(
    step: ProgramStep[StepReference], env: DdEnvironment, catalog: DatasetCatalog
) -> int:
    return 0


def idcams(
    step: ProgramStep[StepReference], env: DdEnvironment, catalog: DatasetCatalog
) -> int:
    sysin = next(d for d in step.dds if d.ddname == _SYSIN)
    commands = parse_idcams("\n".join(sysin.in_stream) + "\n")
    return run_idcams(commands, env, catalog)


UTILITIES: Mapping[ProgramRef, Utility] = {
    ProgramRef("IEFBR14"): iefbr14,
    ProgramRef("IDCAMS"): idcams,
}
