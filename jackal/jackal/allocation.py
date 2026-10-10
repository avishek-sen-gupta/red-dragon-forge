"""A step's DDs, allocated before its program runs and disposed after it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TypeAlias

from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.catalog import Dataset, DatasetCatalog
from jackal.model import (
    DD,
    DdName,
    DispStatus,
    DummyDSN,
    InStreamDSN,
    NoDSN,
    ProgramStep,
    QualifiedStep,
    StepReference,
)

LOAD_LIBRARIES: frozenset[DdName] = frozenset({DdName("STEPLIB"), DdName("JOBLIB")})

_CARD = 80


class Positioning(Enum):
    START = "START"
    END = "END"


@dataclass(frozen=True)
class DatasetAllocation:
    dataset: Dataset
    positioning: Positioning

    def path(self) -> Path:
        return self.dataset.path

    def appends(self) -> bool:
        return self.positioning is Positioning.END


@dataclass(frozen=True)
class InStreamAllocation:
    lines: tuple[str, ...]
    cards: Path

    def path(self) -> Path:
        return self.cards

    def appends(self) -> bool:
        return False


@dataclass(frozen=True)
class DummyAllocation:
    sink: Path

    def path(self) -> Path:
        return self.sink

    def appends(self) -> bool:
        return False


@dataclass(frozen=True)
class SysoutAllocation:
    sink: Path

    def path(self) -> Path:
        return self.sink

    def appends(self) -> bool:
        return False


Allocation: TypeAlias = (
    DatasetAllocation | InStreamAllocation | DummyAllocation | SysoutAllocation
)


@dataclass(frozen=True)
class DdEnvironment:
    entries: tuple[tuple[DdName, Allocation], ...]

    def get(self, ddname: DdName) -> Allocation:
        return dict(self.entries)[ddname]

    def dataset(self, ddname: DdName) -> Dataset:
        match self.get(ddname):
            case DatasetAllocation(dataset=dataset):
                return dataset
            case other:
                raise TypeError(f"DD {ddname.text} is {type(other).__name__}")

    def paths(self) -> Mapping[str, Path]:
        return {name.text: allocation.path() for name, allocation in self.entries}

    def appended(self) -> frozenset[DdName]:
        return frozenset(
            name for name, allocation in self.entries if allocation.appends()
        )


def _sink(qualified: QualifiedStep, dd: DD[StepReference], kind: str) -> Path:
    return Path(kind) / f"{qualified.rendered()}.{dd.ddname.text}"


def _written(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _cards(lines: tuple[str, ...]) -> bytes:
    text = "".join(line[:_CARD].ljust(_CARD) for line in lines)
    return bytes(EbcdicTable.ascii_to_ebcdic(text.encode("ascii")))


def _allocated(
    qualified: QualifiedStep, dd: DD[StepReference], catalog: DatasetCatalog
) -> Allocation:
    match dd.dsn:
        case InStreamDSN():
            sink = catalog.workdir / _sink(qualified, dd, "instream")
            return InStreamAllocation(
                dd.in_stream, _written(sink, _cards(dd.in_stream))
            )
        case DummyDSN():
            return DummyAllocation(
                _written(catalog.workdir / _sink(qualified, dd, "dummy"), b"")
            )
        case _:
            return _named(qualified, dd, catalog)


def _positioning(dd: DD[StepReference]) -> Positioning:
    if dd.disposition().status is DispStatus.MOD:
        return Positioning.END
    return Positioning.START


def _named(
    qualified: QualifiedStep, dd: DD[StepReference], catalog: DatasetCatalog
) -> Allocation:
    if dd.sysout and isinstance(dd.dsn, NoDSN):
        return SysoutAllocation(
            _written(catalog.workdir / _sink(qualified, dd, "sysout"), b"")
        )
    return DatasetAllocation(catalog.allocate(dd), _positioning(dd))


def allocate(
    qualified: QualifiedStep, step: ProgramStep[StepReference], catalog: DatasetCatalog
) -> DdEnvironment:
    return DdEnvironment(
        tuple(
            (dd.ddname, _allocated(qualified, dd, catalog))
            for dd in step.dds
            if dd.ddname not in LOAD_LIBRARIES
        )
    )


def _released(allocation: Allocation) -> None:
    match allocation:
        case DatasetAllocation():
            return
        case _:
            allocation.path().unlink(missing_ok=True)


def _apply_disp(step: ProgramStep[StepReference], catalog: DatasetCatalog) -> None:
    for dd in (d for d in step.dds if d.ddname not in LOAD_LIBRARIES):
        catalog.dispose(dd)


def _release_all(env: DdEnvironment) -> None:
    for _, allocation in env.entries:
        _released(allocation)


def dispose(
    step: ProgramStep[StepReference], env: DdEnvironment, catalog: DatasetCatalog
) -> None:
    _apply_disp(step, catalog)
    _release_all(env)
