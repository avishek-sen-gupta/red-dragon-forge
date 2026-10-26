"""COBOL's file handler over catalogued datasets: each file opens as its ASSIGN name is bound and its label allows."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from pathlib import Path

from catnip.catalog_stores import Table
from catnip.dataset import Dataset, Relabeller
from catnip.labels import (
    VARIABLE,
    DatasetLabel,
    Label,
    LabelPending,
    PathView,
    SequentialLabel,
)
from catnip.variable_records import VariableRecordDriver
from cobol_asg.file_enums import FileOrganization, OpenMode
from infrastructure.zos.access_methods.access_result import (
    AccessCondition,
    AccessResult,
)
from infrastructure.zos.access_methods.file_drivers import FileOrganizationDriver
from interpreter.cobol.io_provider import IOResult
from interpreter.cobol.real_file_provider import RealFileIOProvider, to_ioresult
from interpreter.record_io.file_frame import FileFrame
from interpreter.record_io.run_inputs import RunInputs
from zos.cobol.io.file_bindings import FileBindings
from zos.cobol.io.label_conflict import LabelConflict
from zos.cobol.io.program_file import ProgramFile
from zos.cobol.io.record_format import (
    FixedFormat,
    ProgramFormat,
    VariableFormat,
    conflicting,
    indexed_conflicts,
    label_for,
)
from zos.cobol.io.record_key import RecordKey

logger = logging.getLogger(__name__)

_LABELLING = frozenset({OpenMode.OUTPUT.value, OpenMode.EXTEND.value})


def variable(label: DatasetLabel) -> bool:
    match label:
        case SequentialLabel():
            return label.recfm in VARIABLE
        case _:
            return False


def _logged(found: Sequence[tuple[str, LabelConflict]]) -> bool:
    for name, conflict in found:
        logger.warning("%s", conflict.described(name))
    return not found


def _agrees(dataset: Dataset, found: Sequence[LabelConflict]) -> bool:
    return _logged(tuple((dataset.dsn, conflict) for conflict in found))


def _through_path(label: DatasetLabel) -> bool:
    match label:
        case PathView():
            return True
        case _:
            return False


def _supported(label: DatasetLabel, mode: str) -> bool:
    return not (_through_path(label) and mode == OpenMode.OUTPUT.value)


def _dataset_driver(
    dataset: Dataset,
    path: Path,
    mode: OpenMode,
    record_length: int,
    by_organization: Callable[[], FileOrganizationDriver],
) -> FileOrganizationDriver:
    if _through_path(dataset.label):
        return dataset.opened(mode)
    if variable(dataset.label):
        return VariableRecordDriver(path, mode, record_length)
    return by_organization()


def _datasets(
    files: Sequence[ProgramFile], bindings: FileBindings
) -> tuple[tuple[str, Dataset], ...]:
    return tuple(
        (f.entry.file_name, bindings.datasets[f.entry.assign_to])
        for f in files
        if f.entry.assign_to in bindings.datasets
    )


class DatasetFileIOProvider(RealFileIOProvider):
    """Opens a file as its ASSIGN name is bound: an appended binding appends; a label the FD contradicts fails with status 39."""

    def __init__(
        self,
        base_dir: Path,
        files: Sequence[ProgramFile],
        bindings: FileBindings,
        relabeller: Relabeller,
    ) -> None:
        super().__init__(
            base_dir,
            inputs=RunInputs(
                file_control=tuple(f.entry for f in files),
                path_overrides=bindings.paths,
            ),
        )
        self._appended_files = frozenset(
            f.entry.file_name for f in files if f.entry.assign_to in bindings.appended
        )
        self._program_files: Mapping[str, ProgramFile] = {
            f.entry.file_name: f for f in files
        }
        self._relabeller = relabeller
        self._datasets: Table[str, Dataset] = Table()
        for name, dataset in _datasets(files, bindings):
            self._datasets.put(name, dataset)

    def _opened_as(self, filename: str, mode: str) -> str:
        if mode == OpenMode.OUTPUT.value and filename in self._appended_files:
            return OpenMode.EXTEND.value
        return mode

    def _supports(self, filename: str, mode: str) -> bool:
        if self._datasets.has(filename):
            return _supported(self._datasets.get(filename).label, mode)
        return True

    def _admits(self, filename: str, mode: str, prime: RecordKey) -> bool:
        if not self._datasets.has(filename):
            return True
        declared = self._program_files[filename]
        if declared.entry.organization is FileOrganization.INDEXED:
            dataset = self._datasets.get(filename)
            return _agrees(
                dataset, indexed_conflicts(declared.fmt, prime, dataset.label)
            )
        return self._admits_sequential(filename, declared.fmt, mode)

    def _admits_sequential(self, filename: str, fmt: ProgramFormat, mode: str) -> bool:
        dataset = self._datasets.get(filename)
        match (dataset.label, fmt):
            case (LabelPending(), FixedFormat() | VariableFormat()) if (
                mode in _LABELLING
            ):
                self._labelled(filename, dataset, label_for(fmt))
                return True
            case _:
                return _agrees(dataset, conflicting(fmt, dataset.label))

    def _labelled(self, filename: str, dataset: Dataset, label: Label) -> None:
        self._relabeller.relabel(dataset, label)
        self._datasets.put(filename, Dataset(dataset.dsn, dataset.path, label))

    def _driver_for(
        self, frame: FileFrame, path: Path, mode: OpenMode
    ) -> FileOrganizationDriver:
        filename = frame.file_name
        by_organization = partial(super()._driver_for, frame, path, mode)
        if not self._datasets.has(filename):
            return by_organization()
        return _dataset_driver(
            self._datasets.get(filename),
            path,
            mode,
            frame.record_length,
            by_organization,
        )

    def _open_file(self, filename: str, mode: str, program: str) -> IOResult:
        opened = self._opened_as(filename, mode)
        if not self._supports(filename, opened):
            return to_ioresult(AccessResult(AccessCondition.OPEN_MODE_NOT_SUPPORTED))
        frame = self._frames[filename]
        prime = frame.prime_key
        if not self._admits(
            filename,
            opened,
            RecordKey(
                prime.offset,
                prime.length,
            ),
        ):
            return to_ioresult(AccessResult(AccessCondition.ATTRIBUTE_CONFLICT))
        return super()._open_file(filename, opened, program)
