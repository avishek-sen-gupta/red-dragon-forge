"""A step's DDs, allocated before its program runs and disposed after it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TypeAlias

from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.catalog import DatasetCatalog, Unallocated
from jackal.dataset import Dataset
from jackal.missing_data import MissingDataStrategy
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
from jackal.results import AllocationFailed, ProgramResult

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

    def added(self, ddname: DdName, allocation: Allocation) -> DdEnvironment:
        return DdEnvironment((*self.entries, (ddname, allocation)))

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


def _positioning(dd: DD[StepReference]) -> Positioning:
    if dd.disposition().status is DispStatus.MOD:
        return Positioning.END
    return Positioning.START


def _placed(
    dd: DD[StepReference], settled: Dataset | AllocationFailed
) -> Allocation | AllocationFailed:
    match settled:
        case AllocationFailed():
            return settled
        case Dataset():
            return DatasetAllocation(settled, _positioning(dd))


@dataclass(frozen=True)
class _Allocator:
    qualified: QualifiedStep
    catalog: DatasetCatalog
    missing_data: MissingDataStrategy

    def remaining(
        self,
        dds: tuple[DD[StepReference], ...],
        done: tuple[DD[StepReference], ...],
        env: DdEnvironment,
    ) -> DdEnvironment | AllocationFailed:
        if not dds:
            return env
        return self._then(dds, done, env, self._allocated(dds[0]))

    def _then(
        self,
        dds: tuple[DD[StepReference], ...],
        done: tuple[DD[StepReference], ...],
        env: DdEnvironment,
        attempt: Allocation | AllocationFailed,
    ) -> DdEnvironment | AllocationFailed:
        match attempt:
            case AllocationFailed():
                _undo(done, env, self.catalog)
                return attempt
            case _:
                return self.remaining(
                    dds[1:], (*done, dds[0]), env.added(dds[0].ddname, attempt)
                )

    def _allocated(self, dd: DD[StepReference]) -> Allocation | AllocationFailed:
        match dd.dsn:
            case InStreamDSN():
                cards = _written(self._sink(dd, "instream"), _cards(dd.in_stream))
                return InStreamAllocation(dd.in_stream, cards)
            case DummyDSN():
                return DummyAllocation(_written(self._sink(dd, "dummy"), b""))
            case _:
                return self._named(dd)

    def _sink(self, dd: DD[StepReference], kind: str) -> Path:
        return self.catalog.workdir / _sink(self.qualified, dd, kind)

    def _named(self, dd: DD[StepReference]) -> Allocation | AllocationFailed:
        if dd.sysout and isinstance(dd.dsn, NoDSN):
            return SysoutAllocation(_written(self._sink(dd, "sysout"), b""))
        return self._dataset(dd)

    def _dataset(self, dd: DD[StepReference]) -> Allocation | AllocationFailed:
        found = self.catalog.allocate(dd)
        match found:
            case Unallocated():
                settled = self.missing_data.settle(self.qualified, found, self.catalog)
                return _placed(dd, settled)
            case Dataset():
                return DatasetAllocation(found, _positioning(dd))


def allocate(
    qualified: QualifiedStep,
    step: ProgramStep[StepReference],
    catalog: DatasetCatalog,
    missing_data: MissingDataStrategy,
) -> DdEnvironment | AllocationFailed:
    dds = tuple(dd for dd in step.dds if dd.ddname not in LOAD_LIBRARIES)
    allocator = _Allocator(qualified, catalog, missing_data)
    return allocator.remaining(dds, (), DdEnvironment(()))


def _undo(
    done: tuple[DD[StepReference], ...], env: DdEnvironment, catalog: DatasetCatalog
) -> None:
    for dd in done:
        catalog.delete_if_new(dd)
    _release_all(env)


def _released(allocation: Allocation) -> None:
    match allocation:
        case DatasetAllocation():
            return
        case _:
            allocation.path().unlink(missing_ok=True)


def _apply_disp(
    step: ProgramStep[StepReference], catalog: DatasetCatalog, result: ProgramResult
) -> None:
    for dd in (d for d in step.dds if d.ddname not in LOAD_LIBRARIES):
        catalog.dispose(dd, result)


def _release_all(env: DdEnvironment) -> None:
    for _, allocation in env.entries:
        _released(allocation)


def dispose(
    step: ProgramStep[StepReference],
    env: DdEnvironment,
    catalog: DatasetCatalog,
    result: ProgramResult,
) -> None:
    _apply_disp(step, catalog, result)
    _release_all(env)
