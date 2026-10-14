"""Imperative shell: the persistent system catalog and the dataset bytes it owns, under one directory."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from catnip.catalog_stores import Table
from catnip.dataset import Dataset
from catnip.gdg import Empty, GdgBase, GdgOrder, Scratch
from catnip.labels import (
    DatasetLabel,
    KsdsLabel,
    Label,
    LabelPending,
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


class _CatalogWire(_Wire):
    entries: tuple[_EntryWire, ...]
    gdgs: tuple[_GdgWire, ...] = ()


def _label_wire(label: DatasetLabel) -> _LabelWire:
    match label:
        case SequentialLabel():
            return _SequentialWire(recfm=label.recfm, lrecl=label.lrecl)
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


class SystemCatalog:
    """Imperative shell: cataloged datasets survive the run, recorded in catalog.json beside their bytes."""

    def __init__(self, root: Path):
        self._root = root
        self._datasets_dir = root / DATASETS_DIR
        self._datasets_dir.mkdir(parents=True, exist_ok=True)
        self._entries: Table[str, Dataset] = Table()
        self._gdgs: Table[str, GdgBase] = Table()
        recorded = self._recorded()
        for entry in recorded.entries:
            self._entries.put(entry.dsn, self._dataset(entry.dsn, entry.label.model()))
        for gdg in recorded.gdgs:
            self._gdgs.put(gdg.name, gdg.model())

    def _recorded(self) -> _CatalogWire:
        path = self._root / CATALOG_FILE
        if not path.exists():
            return _CatalogWire(entries=())
        return _CatalogWire.model_validate_json(path.read_text())

    def _dataset(self, dsn: str, label: DatasetLabel) -> Dataset:
        return Dataset(dsn, self._datasets_dir / dsn, label)

    def lookup(self, dsn: str) -> Dataset | NotCataloged:
        return self._entries.get(dsn) if self._entries.has(dsn) else NotCataloged()

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
        self._entries.take(dsn).path.unlink(missing_ok=True)
        self._write()

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
        (self._root / CATALOG_FILE).write_text(
            _CatalogWire(entries=entries, gdgs=gdgs).model_dump_json(indent=2)
        )
