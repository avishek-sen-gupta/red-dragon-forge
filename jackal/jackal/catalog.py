"""One job's dataset catalog: the system catalog's datasets, plus the job's temps and passed datasets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jackal.catalog_stores import Table
from jackal.dataset import Dataset, Relabeller
from jackal.gdg import GdgBase
from jackal.labels import Label, LabelPending
from jackal.model import (
    DD,
    DSN,
    DirectDSN,
    DispAbnormal,
    DispNormal,
    DispStatus,
    GenerationDSN,
    ResolvedDisp,
    StepReference,
    TempRef,
)
from jackal.results import Abended, AllocationError, Completed, ProgramResult
from jackal.system_catalog import NotCataloged, SystemCatalog
from jackal.system_catalog_removal import remove_cataloged


@dataclass(frozen=True)
class Allocated:
    dataset: Dataset
    existed: bool


@dataclass(frozen=True)
class Unallocated:
    dd: DD[StepReference]
    error: AllocationError


def _temp_name(alias: str) -> str:
    return f"&&{alias}"


def _empty(dataset: Dataset) -> Dataset:
    dataset.path.write_bytes(b"")
    return dataset


def _passes(disp: ResolvedDisp, result: ProgramResult) -> bool:
    match result:
        case Completed():
            return disp.normal is DispNormal.PASS
        case Abended():
            return False


def _deletes(disp: ResolvedDisp, result: ProgramResult) -> bool:
    match result:
        case Completed():
            return disp.normal is DispNormal.DELETE
        case Abended():
            return disp.abnormal is DispAbnormal.DELETE


class DatasetCatalog(Relabeller):
    """Imperative shell: one job's view of the system catalog, with its temps, passed datasets and scratch."""

    def __init__(self, scratch: Path, system: SystemCatalog):
        self._scratch = scratch
        self._system = system
        self._temps: Table[str, Dataset] = Table()
        self._passed: Table[str, str] = Table()

    def resolve(self, dsn: str) -> Dataset | NotCataloged:
        return self._system.lookup(dsn)

    def allocate(self, dd: DD[StepReference]) -> Allocated | Unallocated:
        match dd.dsn:
            case TempRef(name=name):
                return self._allocate_temp(dd, name)
            case _:
                return self._allocate_direct(dd, dd.dsn.dataset_name())

    def created_empty(self, dd: DD[StepReference]) -> Dataset:
        match dd.dsn:
            case TempRef(name=name):
                temp = _empty(self._temp_dataset(name))
                return self._temps.put(temp.dsn, temp)
            case _:
                return self._system.create(dd.dsn.dataset_name(), LabelPending())

    def _temp_dataset(self, alias: str) -> Dataset:
        name = _temp_name(alias)
        return Dataset(dsn=name, path=self._scratch / name, label=LabelPending())

    def relabel(self, dataset: Dataset, label: Label) -> None:
        match self._system.lookup(dataset.dsn):
            case Dataset():
                self._system.relabel(dataset.dsn, label)
            case NotCataloged():
                self._temps.put(dataset.dsn, Dataset(dataset.dsn, dataset.path, label))

    def _allocate_temp(
        self, dd: DD[StepReference], name: str
    ) -> Allocated | Unallocated:
        if dd.disposition().status is DispStatus.NEW:
            return self._new_temp(dd, name)
        if not self._temps.has(_temp_name(name)):
            return Unallocated(dd, AllocationError.TEMP_NOT_CREATED)
        return Allocated(self._temps.get(_temp_name(name)), existed=True)

    def _new_temp(self, dd: DD[StepReference], name: str) -> Allocated | Unallocated:
        if self._temps.has(_temp_name(name)):
            return Unallocated(dd, AllocationError.DUPLICATE_NAME)
        return Allocated(self.created_empty(dd), existed=False)

    def _allocate_direct(
        self, dd: DD[StepReference], name: str
    ) -> Allocated | Unallocated:
        if dd.disposition().status is DispStatus.NEW:
            return self._new_direct(dd, name)
        return self._existing(dd, name)

    def _new_direct(self, dd: DD[StepReference], name: str) -> Allocated | Unallocated:
        match self._system.lookup(name):
            case Dataset():
                return Unallocated(dd, AllocationError.DUPLICATE_NAME)
            case NotCataloged():
                return Allocated(self.created_empty(dd), existed=False)

    def _existing(self, dd: DD[StepReference], name: str) -> Allocated | Unallocated:
        match self._system.lookup(name):
            case Dataset() as found:
                return Allocated(found, existed=True)
            case NotCataloged():
                return self._missing(dd)

    def _missing(self, dd: DD[StepReference]) -> Allocated | Unallocated:
        if dd.disposition().status is DispStatus.MOD:
            return Allocated(self.created_empty(dd), existed=False)
        return Unallocated(dd, AllocationError.DATASET_NOT_FOUND)

    def delete_created(self, dd: DD[StepReference]) -> None:
        self._delete(dd.dsn)

    def gdg(self, name: str) -> GdgBase | NotCataloged:
        return self._system.gdg(name)

    def define(self, dsn: str, label: Label) -> Dataset:
        self._uncataloged(dsn)
        return self._system.create(dsn, label)

    def define_gdg(self, base: GdgBase) -> GdgBase:
        self._uncataloged(base.name)
        return self._system.define_gdg(base)

    def _uncataloged(self, name: str) -> None:
        match (self._system.lookup(name), self._system.gdg(name)):
            case (NotCataloged(), NotCataloged()):
                return
            case _:
                raise ValueError(f"DSN already cataloged: {name}")

    def delete_dsn(self, dsn: str) -> bool:
        match self._system.lookup(dsn):
            case Dataset():
                remove_cataloged(self._system, dsn)
                return True
            case NotCataloged():
                return False

    def dispose(
        self,
        dd: DD[StepReference],
        disposition: ResolvedDisp,
        existed: bool,
        result: ProgramResult,
    ) -> None:
        if _deletes(disposition, result):
            self._delete(dd.dsn)
            return
        self._pass_or_receive(dd, disposition, existed, result)

    def _pass_or_receive(
        self,
        dd: DD[StepReference],
        disposition: ResolvedDisp,
        existed: bool,
        result: ProgramResult,
    ) -> None:
        match dd.dsn:
            case DirectDSN() | GenerationDSN():
                self._passed_on(dd.dsn.dataset_name(), disposition, existed, result)
            case _:
                return

    def _passed_on(
        self,
        name: str,
        disposition: ResolvedDisp,
        existed: bool,
        result: ProgramResult,
    ) -> None:
        if _passes(disposition, result) and self._passable(name, existed):
            self._passed.put(name, name)
            return
        self._received(name)

    def _passable(self, name: str, existed: bool) -> bool:
        return not existed or self._passed.has(name)

    def _received(self, name: str) -> None:
        if self._passed.has(name):
            self._passed.take(name)

    def _delete(self, dsn: DSN[StepReference]) -> None:
        match dsn:
            case TempRef(name=name):
                self._delete_temp(name)
            case _:
                self._delete_direct(dsn)

    def _delete_direct(self, dsn: DSN[StepReference]) -> None:
        match dsn:
            case DirectDSN() | GenerationDSN():
                self.delete_dsn(dsn.dataset_name())
                self._received(dsn.dataset_name())
            case _:
                return

    def _delete_temp(self, name: str) -> None:
        if self._temps.has(_temp_name(name)):
            self._temps.take(_temp_name(name)).path.unlink(missing_ok=True)

    def end_job(self) -> None:
        for temp in self._temps.drain():
            temp.path.unlink(missing_ok=True)
        for passed in self._passed.drain():
            self.delete_dsn(passed)

    @property
    def workdir(self) -> Path:
        return self._scratch
