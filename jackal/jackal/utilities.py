"""Emulated utility programs (no COBOL load module)."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from jackal.catalog import DatasetCatalog
from jackal.dsn import DdName, DirectDSN, TempRef
from jackal.idcams.executor import run_idcams
from jackal.idcams.parser import parse_idcams
from jackal.model import ProgramRef, ProgramStep, QualifiedStep

Utility = Callable[[ProgramStep[QualifiedStep], DatasetCatalog], int]

_SYSIN = DdName("SYSIN")


def iefbr14(step: ProgramStep[QualifiedStep], catalog: DatasetCatalog) -> int:
    datasets = tuple(
        dd
        for dd in step.dds
        if not dd.sysout and isinstance(dd.dsn, DirectDSN | TempRef)
    )
    for dd in datasets:
        catalog.allocate(dd)
    for disposed in datasets:
        catalog.dispose(disposed)
    return 0


def idcams(step: ProgramStep[QualifiedStep], catalog: DatasetCatalog) -> int:
    sysin = next(d for d in step.dds if d.ddname == _SYSIN)
    commands = parse_idcams("\n".join(sysin.in_stream) + "\n")
    return run_idcams(commands, step.dds, catalog)


UTILITIES: Mapping[ProgramRef, Utility] = {
    ProgramRef("IEFBR14"): iefbr14,
    ProgramRef("IDCAMS"): idcams,
}
