"""A step's DDs, allocated before its program runs and disposed after it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import TypeAlias

from interpreter.cobol.ebcdic_table import EbcdicTable
from jackal.catalog import Allocated, DatasetCatalog, Unallocated
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
    ResolvedDisp,
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
    existed: bool
    disposition: ResolvedDisp

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


MemberAllocation: TypeAlias = (
    DatasetAllocation | InStreamAllocation | DummyAllocation | SysoutAllocation
)


@dataclass(frozen=True)
class ConcatenatedAllocation:
    """Members read in order as one dataset; the first stands for the whole, as a referback does."""

    members: tuple[MemberAllocation, ...]

    def path(self) -> Path:
        return self.members[0].path()

    def appends(self) -> bool:
        return False


Allocation: TypeAlias = MemberAllocation | ConcatenatedAllocation


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


@dataclass(frozen=True)
class _Part:
    dd: DD[StepReference]
    allocation: MemberAllocation


def _member_dds(dd: DD[StepReference]) -> tuple[DD[StepReference], ...]:
    members = tuple(DD(dd.ddname, m.dsn, m.disp, m.in_stream) for m in dd.concatenated)
    return (replace(dd, concatenated=()), *members)


def _parts(dd: DD[StepReference], allocation: Allocation) -> tuple[_Part, ...]:
    match allocation:
        case ConcatenatedAllocation(members=members):
            return tuple(map(_Part, _member_dds(dd), members))
        case _:
            return (_Part(dd, allocation),)


def _all_parts(
    dds: Sequence[DD[StepReference]], env: DdEnvironment
) -> tuple[_Part, ...]:
    return tuple(part for dd in dds for part in _parts(dd, env.get(dd.ddname)))


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


def _dataset_allocation(
    dd: DD[StepReference], allocated: Allocated
) -> MemberAllocation:
    return DatasetAllocation(
        allocated.dataset,
        _positioning(dd),
        allocated.existed,
        dd.disposition().resolved(allocated.existed),
    )


def _placed(
    dd: DD[StepReference], settled: Dataset | AllocationFailed
) -> MemberAllocation | AllocationFailed:
    match settled:
        case AllocationFailed():
            return settled
        case Dataset():
            return _dataset_allocation(dd, Allocated(settled, existed=True))


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
        if dd.concatenated:
            return self._members(_member_dds(dd), ())
        return self._single(dd)

    def _members(
        self, dds: tuple[DD[StepReference], ...], done: tuple[_Part, ...]
    ) -> ConcatenatedAllocation | AllocationFailed:
        if not dds:
            return ConcatenatedAllocation(tuple(part.allocation for part in done))
        match self._single(dds[0]):
            case AllocationFailed() as failed:
                _undo_parts(done, self.catalog)
                return failed
            case allocation:
                return self._members(dds[1:], (*done, _Part(dds[0], allocation)))

    def _single(self, dd: DD[StepReference]) -> MemberAllocation | AllocationFailed:
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

    def _named(self, dd: DD[StepReference]) -> MemberAllocation | AllocationFailed:
        if dd.sysout and isinstance(dd.dsn, NoDSN):
            return SysoutAllocation(_written(self._sink(dd, "sysout"), b""))
        return self._dataset(dd)

    def _dataset(self, dd: DD[StepReference]) -> MemberAllocation | AllocationFailed:
        found = self.catalog.allocate(dd)
        match found:
            case Unallocated():
                settled = self.missing_data.settle(self.qualified, found, self.catalog)
                return _placed(dd, settled)
            case Allocated():
                return _dataset_allocation(dd, found)


def allocate(
    qualified: QualifiedStep,
    step: ProgramStep[StepReference],
    catalog: DatasetCatalog,
    missing_data: MissingDataStrategy,
) -> DdEnvironment | AllocationFailed:
    dds = tuple(dd for dd in step.dds if dd.ddname not in LOAD_LIBRARIES)
    allocator = _Allocator(qualified, catalog, missing_data)
    return allocator.remaining(dds, (), DdEnvironment(()))


def _created(allocation: MemberAllocation) -> tuple[Dataset, ...]:
    match allocation:
        case DatasetAllocation(dataset=dataset, existed=False):
            return (dataset,)
        case _:
            return ()


def _undo_parts(parts: Sequence[_Part], catalog: DatasetCatalog) -> None:
    for dd, dataset in ((p.dd, d) for p in parts for d in _created(p.allocation)):
        catalog.delete_created(dd, dataset)
    for part in parts:
        _released(part.allocation)


def _undo(
    done: tuple[DD[StepReference], ...], env: DdEnvironment, catalog: DatasetCatalog
) -> None:
    _undo_parts(_all_parts(done, env), catalog)


def _released(allocation: MemberAllocation) -> None:
    match allocation:
        case DatasetAllocation():
            return
        case _:
            allocation.path().unlink(missing_ok=True)


def _disposed(part: _Part, catalog: DatasetCatalog, result: ProgramResult) -> None:
    match part.allocation:
        case DatasetAllocation(
            dataset=dataset, disposition=disposition, existed=existed
        ):
            catalog.dispose(part.dd, dataset, disposition, existed, result)
        case _:
            return


def dispose(
    step: ProgramStep[StepReference],
    env: DdEnvironment,
    catalog: DatasetCatalog,
    result: ProgramResult,
) -> None:
    for part in _step_parts(step, env):
        _disposed(part, catalog, result)


def release(step: ProgramStep[StepReference], env: DdEnvironment) -> None:
    for part in _step_parts(step, env):
        _released(part.allocation)


def _step_parts(
    step: ProgramStep[StepReference], env: DdEnvironment
) -> tuple[_Part, ...]:
    dds = tuple(d for d in step.dds if d.ddname not in LOAD_LIBRARIES)
    return _all_parts(dds, env)
