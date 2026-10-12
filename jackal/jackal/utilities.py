"""Emulated utility programs (no COBOL load module)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from jackal.allocation import DdEnvironment
from jackal.catalog import DatasetCatalog
from jackal.idcams.commands import Command
from jackal.idcams.executor import run_idcams
from jackal.idcams.parser import parse_idcams
from jackal.model import DdName, ProgramRef, ProgramStep, StepReference

Utility = Callable[[ProgramStep[StepReference], DdEnvironment, DatasetCatalog], int]

_SYSIN = DdName("SYSIN")
_LEFT_MARGIN = 2
_RIGHT_MARGIN = 72


def _within_margins(record: str) -> str:
    return record[_LEFT_MARGIN - 1 : _RIGHT_MARGIN]


def iefbr14(
    step: ProgramStep[StepReference], env: DdEnvironment, catalog: DatasetCatalog
) -> int:
    return 0


def idcams(
    step: ProgramStep[StepReference], env: DdEnvironment, catalog: DatasetCatalog
) -> int:
    sysin = next(d for d in step.dds if d.ddname == _SYSIN)
    return run_idcams(sysin_commands(sysin.in_stream), env, catalog)


def sysin_commands(records: Sequence[str]) -> tuple[Command, ...]:
    return parse_idcams("".join(f"{_within_margins(r)}\n" for r in records))


UTILITIES: Mapping[ProgramRef, Utility] = {
    ProgramRef("IEFBR14"): iefbr14,
    ProgramRef("IDCAMS"): idcams,
}
