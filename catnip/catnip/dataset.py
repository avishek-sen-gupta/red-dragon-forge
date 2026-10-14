"""A dataset: its name, the file holding its bytes, and its label."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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
from interpreter.cobol.alternate_index_driver import open_alternate_index_driver
from interpreter.cobol.file_drivers import FileOrganizationDriver, open_driver


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
                return _through_path(self.path, mode, self.label)
            case _:
                return _sequential(self.path, mode, self.label)


def _indexed(path: Path, mode: OpenMode, label: KsdsLabel) -> FileOrganizationDriver:
    return open_driver(
        FileOrganization.INDEXED,
        path,
        mode,
        label.lrecl,
        label.key_offset,
        label.key_length,
    )


def _through_path(
    path: Path, mode: OpenMode, label: PathView
) -> FileOrganizationDriver:
    return open_alternate_index_driver(
        path,
        mode,
        label.base.lrecl,
        label.base.key_offset,
        label.base.key_length,
        label.key_offset,
        label.key_length,
        label.unique,
    )


def _sequential(
    path: Path, mode: OpenMode, label: SequentialLabel | LabelPending
) -> FileOrganizationDriver:
    match label:
        case SequentialLabel():
            return _labelled_sequential(path, mode, label)
        case LabelPending():
            return open_driver(FileOrganization.SEQUENTIAL, path, mode, 0, 0, 0)


def _labelled_sequential(
    path: Path, mode: OpenMode, label: SequentialLabel
) -> FileOrganizationDriver:
    if label.recfm in VARIABLE:
        return VariableRecordDriver(path, mode, 0)
    return open_driver(FileOrganization.SEQUENTIAL, path, mode, label.lrecl, 0, 0)


class Relabeller(Protocol):
    def relabel(self, dataset: Dataset, label: Label) -> None: ...
