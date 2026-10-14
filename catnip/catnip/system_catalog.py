"""Imperative shell: the persistent system catalog and the dataset bytes it owns, under one directory."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from catnip.alternate_index import AlternateIndex
from catnip.catalog_error import CatalogError
from catnip.catalog_path import CatalogPath
from catnip.catalog_stores import Table
from catnip.dataset import Dataset
from catnip.gdg import Empty, GdgBase, GdgOrder, Scratch
from catnip.labels import (
    DatasetLabel,
    KsdsLabel,
    Label,
    LabelPending,
    PathView,
    RecordFormat,
    SequentialLabel,
)
from pydantic import BaseModel, ConfigDict, Field

CATALOG_FILE = "catalog.json"
DATASETS_DIR = "datasets"


@dataclass(frozen=True)
class NotCataloged:
    pass


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _SequentialWire(_Wire):
    kind: Literal["sequential"] = "sequential"
    recfm: RecordFormat
    lrecl: int

    def model(self) -> DatasetLabel:
        return SequentialLabel(self.recfm, self.lrecl)


class _KsdsWire(_Wire):
    kind: Literal["ksds"] = "ksds"
    lrecl: int
    key_offset: int
    key_length: int

    def model(self) -> DatasetLabel:
        return KsdsLabel(self.lrecl, self.key_offset, self.key_length)


class _PendingWire(_Wire):
    kind: Literal["pending"] = "pending"

    def model(self) -> DatasetLabel:
        return LabelPending()


_LabelWire = _SequentialWire | _KsdsWire | _PendingWire


class _EntryWire(_Wire):
    dsn: str
    label: _LabelWire = Field(discriminator="kind")


class _GdgWire(_Wire):
    name: str
    limit: int
    empty: Empty
    scratch: Scratch
    order: GdgOrder = GdgOrder.LIFO
    generations: tuple[int, ...]

    def model(self) -> GdgBase:
        return GdgBase(
            self.name,
            self.limit,
            self.empty,
            self.scratch,
            self.order,
            self.generations,
        )


def _gdg_wire(base: GdgBase) -> _GdgWire:
    return _GdgWire(
        name=base.name,
        limit=base.limit,
        empty=base.empty,
        scratch=base.scratch,
        order=base.order,
        generations=base.generations,
    )


class _AixWire(_Wire):
    dsn: str
    base: str
    key_offset: int
    key_length: int
    unique: bool

    def model(self) -> AlternateIndex:
        return AlternateIndex(
            self.dsn, self.base, self.key_offset, self.key_length, self.unique
        )


def _aix_wire(aix: AlternateIndex) -> _AixWire:
    return _AixWire(
        dsn=aix.dsn,
        base=aix.base,
        key_offset=aix.key_offset,
        key_length=aix.key_length,
        unique=aix.unique,
    )


class _PathWire(_Wire):
    dsn: str
    aix: str

    def model(self) -> CatalogPath:
        return CatalogPath(self.dsn, self.aix)


class _CatalogWire(_Wire):
    entries: tuple[_EntryWire, ...]
    gdgs: tuple[_GdgWire, ...] = ()
    aixs: tuple[_AixWire, ...] = ()
    paths: tuple[_PathWire, ...] = ()


def _label_wire(label: DatasetLabel) -> _LabelWire:
    match label:
        case SequentialLabel():
            return _SequentialWire(recfm=label.recfm, lrecl=label.lrecl)
        case _:
            return _stored_wire(label)


def _stored_wire(label: KsdsLabel | LabelPending | PathView) -> _LabelWire:
    match label:
        case PathView():
            raise CatalogError("a path's view is never stored as a dataset label")
        case _:
            return _keyed_or_pending_wire(label)


def _keyed_or_pending_wire(label: KsdsLabel | LabelPending) -> _LabelWire:
    match label:
        case KsdsLabel():
            return _KsdsWire(
                lrecl=label.lrecl,
                key_offset=label.key_offset,
                key_length=label.key_length,
            )
        case LabelPending():
            return _PendingWire()


def _ksds(dataset: Dataset) -> KsdsLabel:
    match dataset.label:
        case KsdsLabel():
            return dataset.label
        case _:
            raise CatalogError(
                f"{dataset.dsn}: an alternate index's base is not a KSDS"
            )


class SystemCatalog:
    """Imperative shell: cataloged datasets survive the run, recorded in catalog.json beside their bytes."""

    def __init__(self, root: Path):
        self._root = root
        self._datasets_dir = root / DATASETS_DIR
        self._datasets_dir.mkdir(parents=True, exist_ok=True)
        self._entries: Table[str, Dataset] = Table()
        self._gdgs: Table[str, GdgBase] = Table()
        self._aixs: Table[str, AlternateIndex] = Table()
        self._paths: Table[str, CatalogPath] = Table()
        recorded = self._recorded()
        self._load_datasets(recorded)
        self._load_indexes(recorded)

    def _load_datasets(self, recorded: _CatalogWire) -> None:
        for entry in recorded.entries:
            self._entries.put(entry.dsn, self._dataset(entry.dsn, entry.label.model()))
        for gdg in recorded.gdgs:
            self._gdgs.put(gdg.name, gdg.model())

    def _load_indexes(self, recorded: _CatalogWire) -> None:
        for aix in recorded.aixs:
            self._aixs.put(aix.dsn, aix.model())
        for path in recorded.paths:
            self._paths.put(path.dsn, path.model())

    def _recorded(self) -> _CatalogWire:
        path = self._root / CATALOG_FILE
        if not path.exists():
            return _CatalogWire(entries=())
        return _CatalogWire.model_validate_json(path.read_text())

    def _dataset(self, dsn: str, label: DatasetLabel) -> Dataset:
        return Dataset(dsn, self._datasets_dir / dsn, label)

    def lookup(self, dsn: str) -> Dataset | NotCataloged:
        if self._entries.has(dsn):
            return self._entries.get(dsn)
        if self._paths.has(dsn):
            return self._through(self._paths.get(dsn))
        return NotCataloged()

    def define_aix(self, aix: AlternateIndex) -> AlternateIndex:
        match self.lookup(aix.base):
            case Dataset(label=KsdsLabel()):
                self._aixs.put(aix.dsn, aix)
                self._write()
                return aix
            case _:
                raise CatalogError(
                    f"{aix.dsn}: base cluster {aix.base} is not a cataloged KSDS"
                )

    def define_path(self, path: CatalogPath) -> Dataset:
        if not self._aixs.has(path.aix):
            raise CatalogError(
                f"{path.dsn}: alternate index {path.aix} is not cataloged"
            )
        self._paths.put(path.dsn, path)
        self._write()
        return self._through(path)

    def _through(self, path: CatalogPath) -> Dataset:
        aix = self._aixs.get(path.aix)
        base = self._entries.get(aix.base)
        return Dataset(
            path.dsn,
            base.path,
            PathView(_ksds(base), aix.key_offset, aix.key_length, aix.unique),
        )

    def gdg(self, name: str) -> GdgBase | NotCataloged:
        return self._gdgs.get(name) if self._gdgs.has(name) else NotCataloged()

    def catalog_gdg(self, base: GdgBase) -> GdgBase:
        self._gdgs.put(base.name, base)
        self._write()
        return base

    def add(self, dsn: str, source: Path, label: Label) -> Dataset:
        dataset = self._dataset(dsn, label)
        shutil.copyfile(source, dataset.path)
        return self._cataloged(dataset)

    def create(self, dsn: str, label: DatasetLabel) -> Dataset:
        dataset = self._dataset(dsn, label)
        dataset.path.write_bytes(b"")
        return self._cataloged(dataset)

    def remove(self, dsn: str) -> None:
        if self._paths.has(dsn):
            self._paths.take(dsn)
        elif self._aixs.has(dsn):
            self._drop_aix(dsn)
        else:
            self._drop_cluster(dsn)
        self._write()

    def _drop_cluster(self, dsn: str) -> None:
        self._entries.take(dsn).path.unlink(missing_ok=True)
        tuple(self._drop_aix(a.dsn) for a in self._aixs.values() if a.base == dsn)

    def _drop_aix(self, dsn: str) -> None:
        self._aixs.take(dsn)
        tuple(self._paths.take(p.dsn) for p in self._paths.values() if p.aix == dsn)

    def relabel(self, dsn: str, label: Label) -> Dataset:
        return self._cataloged(self._dataset(dsn, label))

    def _cataloged(self, dataset: Dataset) -> Dataset:
        self._entries.put(dataset.dsn, dataset)
        self._write()
        return dataset

    def _write(self) -> None:
        entries = tuple(
            _EntryWire(dsn=d.dsn, label=_label_wire(d.label))
            for d in self._entries.values()
        )
        gdgs = tuple(_gdg_wire(base) for base in self._gdgs.values())
        aixs = tuple(_aix_wire(aix) for aix in self._aixs.values())
        paths = tuple(
            _PathWire(dsn=path.dsn, aix=path.aix) for path in self._paths.values()
        )
        (self._root / CATALOG_FILE).write_text(
            _CatalogWire(
                entries=entries, gdgs=gdgs, aixs=aixs, paths=paths
            ).model_dump_json(indent=2)
        )
