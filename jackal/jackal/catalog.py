"""One job's dataset catalog: the system catalog's datasets, plus the job's temps and passed datasets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import reduce
from pathlib import Path
from typing import TypeAlias

from catnip.catalog_stores import Table
from catnip.dataset import Dataset, Relabeller
from catnip.gdg import GdgBase, RequestedOrder, relative_generation
from catnip.labels import DatasetLabel, Label, LabelPending
from catnip.system_catalog import NotCataloged, SystemCatalog
from catnip.system_catalog_removal import remove_cataloged
from jackal.dcb_label import coded_label, liked_label
from jackal.model import (
    DD,
    DSN,
    ConcatMember,
    DirectDSN,
    DispAbnormal,
    DispNormal,
    DispStatus,
    GenerationDSN,
    NoDSN,
    NullifiedValue,
    ResolvedDisp,
    StepReference,
    TempRef,
)
from jackal.results import Abended, AllocationError, Completed, ProgramResult
from jackal.value_parts import Value, resolve


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


_LabelRule: TypeAlias = Callable[
    [Value | NullifiedValue, Value | NullifiedValue, DatasetLabel], DatasetLabel
]


def _requested_order(coded: Value | NullifiedValue) -> RequestedOrder:
    match coded:
        case NullifiedValue() | ():
            return RequestedOrder.USECATLG
        case _:
            return RequestedOrder(resolve(coded))


def _parts(dd: DD[StepReference]) -> tuple[ConcatMember[StepReference], ...]:
    return (ConcatMember(dd.dsn, dd.disp, dd.in_stream), *dd.concatenated)


def _empty(dataset: Dataset) -> Dataset:
    dataset.path.write_bytes(b"")
    return dataset


def _passes(disp: ResolvedDisp, result: ProgramResult) -> bool:
    match result:
        case Completed():
            return disp.normal is DispNormal.PASS
        case Abended():
            return False


def _catalogs(disp: ResolvedDisp, result: ProgramResult) -> bool:
    match result:
        case Completed():
            return disp.normal is DispNormal.CATLG
        case Abended():
            return disp.abnormal is DispAbnormal.CATLG


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
        self._found: Table[str, tuple[int, ...]] = Table()

    def resolve(self, dsn: str) -> Dataset | NotCataloged:
        return self._system.lookup(dsn)

    def allocate(self, dd: DD[StepReference]) -> Allocated | Unallocated:
        match dd.dsn:
            case TempRef(name=name):
                return self._allocate_temp(dd, name)
            case GenerationDSN():
                return self._allocate_generation(dd, dd.dsn)
            case _:
                return self._allocate_direct(dd, dd.dsn.dataset_name())

    def _allocate_generation(
        self, dd: DD[StepReference], dsn: GenerationDSN
    ) -> Allocated | Unallocated:
        match self._generation(dsn):
            case AllocationError() as error:
                return Unallocated(dd, error)
            case str() as name:
                return self._allocate_direct(dd, name)

    def _generation(self, dsn: GenerationDSN) -> str | AllocationError:
        match self._system.gdg(dsn.base_name()):
            case NotCataloged():
                return AllocationError.GDG_BASE_NOT_FOUND
            case GdgBase() as base:
                return self._numbered(base, self._numbers(base, dsn))

    def _numbered(
        self, base: GdgBase, numbers: tuple[int, ...]
    ) -> str | AllocationError:
        if not numbers:
            return AllocationError.DATASET_NOT_FOUND
        return base.dataset_name(numbers[0])

    def _numbers(self, base: GdgBase, dsn: GenerationDSN) -> tuple[int, ...]:
        return relative_generation(self._active(base), dsn.relative)

    def _active(self, base: GdgBase) -> tuple[int, ...]:
        if not self._found.has(base.name):
            self._found.put(base.name, base.generations)
        return self._found.get(base.name)

    def generations_expanded(self, dd: DD[StepReference]) -> DD[StepReference]:
        requested = _requested_order(dd.gdg_order)
        head, *rest = (
            p for part in _parts(dd) for p in self._expanded(part, requested)
        )
        return replace(
            dd,
            dsn=head.dsn,
            disp=head.disp,
            in_stream=head.in_stream,
            concatenated=tuple(rest),
        )

    def _expanded(
        self, part: ConcatMember[StepReference], requested: RequestedOrder
    ) -> tuple[ConcatMember[StepReference], ...]:
        match part.dsn:
            case DirectDSN() as dsn:
                return self._all_generations(part, dsn, requested)
            case _:
                return (part,)

    def _all_generations(
        self,
        part: ConcatMember[StepReference],
        dsn: DirectDSN,
        requested: RequestedOrder,
    ) -> tuple[ConcatMember[StepReference], ...]:
        match self._system.gdg(dsn.dataset_name()):
            case GdgBase() as base:
                return self._each_generation(part, dsn, base, requested)
            case NotCataloged():
                return (part,)

    def _each_generation(
        self,
        part: ConcatMember[StepReference],
        dsn: DirectDSN,
        base: GdgBase,
        requested: RequestedOrder,
    ) -> tuple[ConcatMember[StepReference], ...]:
        relatives = base.all_relatives(self._active(base), requested)
        if not relatives:
            return (part,)
        return tuple(
            replace(part, dsn=GenerationDSN(dsn.name, relative))
            for relative in relatives
        )

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
        match self._label(dd):
            case AllocationError() as error:
                return Unallocated(dd, error)
            case label:
                return Allocated(self._created_temp(name, label), existed=False)

    def _created_temp(self, alias: str, label: DatasetLabel) -> Dataset:
        temp = _empty(self._temp_dataset(alias))
        return self._temps.put(temp.dsn, Dataset(temp.dsn, temp.path, label))

    def _label(self, dd: DD[StepReference]) -> DatasetLabel | AllocationError:
        match (dd.dcb.model, dd.dcb.like):
            case (NoDSN(), DirectDSN() as like):
                return self._labelled(dd, liked_label, like)
            case (model, _):
                return self._labelled(dd, coded_label, model)

    def _labelled(
        self, dd: DD[StepReference], rule: _LabelRule, model: DSN[StepReference]
    ) -> DatasetLabel | AllocationError:
        match self._model_label(model):
            case AllocationError() as error:
                return error
            case label:
                return rule(dd.dcb.recfm, dd.dcb.lrecl, label)

    def _model_label(self, model: DSN[StepReference]) -> DatasetLabel | AllocationError:
        match model:
            case DirectDSN():
                return self._cataloged_label(model.dataset_name())
            case _:
                return LabelPending()

    def _cataloged_label(self, name: str) -> DatasetLabel | AllocationError:
        match self._system.lookup(name):
            case Dataset() as found:
                return found.label
            case NotCataloged():
                return AllocationError.DATASET_NOT_FOUND

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
                return self._created(dd, name)

    def _created(self, dd: DD[StepReference], name: str) -> Allocated | Unallocated:
        match self._label(dd):
            case AllocationError() as error:
                return Unallocated(dd, error)
            case label:
                return Allocated(self._system.create(name, label), existed=False)

    def _existing(self, dd: DD[StepReference], name: str) -> Allocated | Unallocated:
        match self._system.lookup(name):
            case Dataset() as found:
                return Allocated(found, existed=True)
            case NotCataloged():
                return self._missing(dd, name)

    def _missing(self, dd: DD[StepReference], name: str) -> Allocated | Unallocated:
        if dd.disposition().status is DispStatus.MOD:
            return self._created(dd, name)
        return Unallocated(dd, AllocationError.DATASET_NOT_FOUND)

    def delete_created(self, dd: DD[StepReference], dataset: Dataset) -> None:
        self._delete(dd.dsn, dataset.dsn)

    def gdg(self, name: str) -> GdgBase | NotCataloged:
        return self._system.gdg(name)

    def define(self, dsn: str, label: Label) -> Dataset:
        self._uncataloged(dsn)
        return self._system.create(dsn, label)

    def define_gdg(self, base: GdgBase) -> GdgBase:
        self._uncataloged(base.name)
        return self._system.catalog_gdg(base)

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
        dataset: Dataset,
        disposition: ResolvedDisp,
        existed: bool,
        result: ProgramResult,
    ) -> None:
        if _deletes(disposition, result):
            self._delete(dd.dsn, dataset.dsn)
            return
        self._pass_or_receive(dd, dataset.dsn, disposition, existed, result)
        if _catalogs(disposition, result):
            self._rolled_in(dd.dsn)

    def _pass_or_receive(
        self,
        dd: DD[StepReference],
        name: str,
        disposition: ResolvedDisp,
        existed: bool,
        result: ProgramResult,
    ) -> None:
        match dd.dsn:
            case DirectDSN() | GenerationDSN():
                self._passed_on(name, disposition, existed, result)
            case _:
                return

    def _rolled_in(self, dsn: DSN[StepReference]) -> None:
        match dsn:
            case GenerationDSN():
                self._generation_rolled_in(dsn)
            case _:
                return

    def _generation_rolled_in(self, dsn: GenerationDSN) -> None:
        match self._system.gdg(dsn.base_name()):
            case GdgBase() as base:
                self._roll(base, self._numbers(base, dsn))
            case NotCataloged():
                return

    def _roll(self, base: GdgBase, numbers: tuple[int, ...]) -> None:
        if not numbers:
            return
        rolled, off = base.rolled_in(numbers[0])
        self._system.catalog_gdg(rolled)
        for name in rolled.scratched(off):
            self.delete_dsn(name)

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

    def _delete(self, dsn: DSN[StepReference], name: str) -> None:
        match dsn:
            case TempRef(name=alias):
                self._delete_temp(alias)
            case _:
                self._generation_deleted(dsn)
                self.delete_dsn(name)
                self._received(name)

    def _generation_deleted(self, dsn: DSN[StepReference]) -> None:
        match dsn:
            case GenerationDSN():
                self._dropped_from_gdg(dsn)
            case _:
                return

    def _dropped_from_gdg(self, dsn: GenerationDSN) -> None:
        match self._system.gdg(dsn.base_name()):
            case GdgBase() as base:
                self._system.catalog_gdg(
                    reduce(GdgBase.without, self._numbers(base, dsn), base)
                )
            case NotCataloged():
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
