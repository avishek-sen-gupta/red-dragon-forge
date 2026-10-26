"""A dataset: its name, the file holding its bytes, and its label."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from catnip.catalog_error import CatalogError
from catnip.labels import (
    VARIABLE,
    DatasetLabel,
    KsdsLabel,
    Label,
    LabelPending,
    PathView,
    SequentialLabel,
)
from catnip.variable_records import VariableRecordDriver
from cobol_asg.file_enums import FileOrganization, OpenMode
from infrastructure.zos.access_methods.alternate_index_driver import (
    open_alternate_index_driver,
)
from infrastructure.zos.access_methods.alternate_key import AlternateKey
from infrastructure.zos.access_methods.file_drivers import (
    FileOrganizationDriver,
    open_driver,
)
from infrastructure.zos.access_methods.prime_key import PrimeKey
from infrastructure.zos.access_methods.record_shape import RecordShape


@dataclass(frozen=True)
class Dataset:
    dsn: str
    path: Path
    label: DatasetLabel

    def opened(self, mode: OpenMode) -> FileOrganizationDriver:
        match self.label:
            case KsdsLabel():
                return _indexed(self.path, mode, self.label)
            case PathView():
                return _through_path(self.dsn, self.path, mode, self.label)
            case _:
                return _sequential(self.path, mode, self.label)


def _indexed(path: Path, mode: OpenMode, label: KsdsLabel) -> FileOrganizationDriver:
    return open_driver(
        path,
        mode,
        RecordShape(
            FileOrganization.INDEXED,
            label.lrecl,
            PrimeKey(label.key_offset, label.key_length),
        ),
    )


def _through_path(
    dsn: str, path: Path, mode: OpenMode, label: PathView
) -> FileOrganizationDriver:
    if mode is OpenMode.OUTPUT:
        raise CatalogError(
            f"{dsn}: OPEN OUTPUT through a path would reload its base cluster "
            f"{label.base_dsn}"
        )
    return open_alternate_index_driver(
        path,
        mode,
        RecordShape(
            FileOrganization.INDEXED,
            label.base.lrecl,
            PrimeKey(label.base.key_offset, label.base.key_length),
        ),
        AlternateKey(PrimeKey(label.key_offset, label.key_length), label.unique),
    )


def _sequential(
    path: Path, mode: OpenMode, label: SequentialLabel | LabelPending
) -> FileOrganizationDriver:
    match label:
        case SequentialLabel():
            return _labelled_sequential(path, mode, label)
        case LabelPending():
            return open_driver(path, mode, _sequential_shape(0))


def _labelled_sequential(
    path: Path, mode: OpenMode, label: SequentialLabel
) -> FileOrganizationDriver:
    if label.recfm in VARIABLE:
        return VariableRecordDriver(path, mode, 0)
    return open_driver(path, mode, _sequential_shape(label.lrecl))


def _sequential_shape(record_length: int) -> RecordShape:
    return RecordShape(FileOrganization.SEQUENTIAL, record_length, PrimeKey())


class Relabeller(Protocol):
    def relabel(self, dataset: Dataset, label: Label) -> None: ...
