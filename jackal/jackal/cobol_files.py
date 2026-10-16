"""jackal's COBOL file handler: red-dragon's, opening each file as its DD was allocated and its label allows."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from itertools import chain
from pathlib import Path

from catnip.catalog_stores import Table
from catnip.dataset import Dataset, Relabeller
from catnip.labels import (
    CARDS,
    VARIABLE,
    DatasetLabel,
    Label,
    LabelPending,
    PathView,
    SequentialLabel,
)
from catnip.variable_records import VariableRecordDriver
from cobol_asg.cobol_statements import FileControlEntry
from cobol_asg.file_enums import FileOrganization, OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from interpreter.cobol.file_drivers import FileOrganizationDriver, open_driver
from interpreter.cobol.io_provider import IOResult
from interpreter.cobol.real_file_provider import RealFileIOProvider, to_ioresult
from jackal.allocation import (
    ConcatenatedAllocation,
    DatasetAllocation,
    DdEnvironment,
    DummyAllocation,
    InStreamAllocation,
    MemberAllocation,
    SysoutAllocation,
)
from jackal.concatenated_records import ConcatenatedDriver
from jackal.label_conflict import LabelConflict
from jackal.record_format import (
    FixedFormat,
    ProgramFormat,
    VariableFormat,
    conflicting,
    indexed_conflicts,
    joining,
    label_for,
)
from jackal.record_key import RecordKey

logger = logging.getLogger(__name__)

_LABELLING = frozenset({OpenMode.OUTPUT.value, OpenMode.EXTEND.value})


@dataclass(frozen=True)
class ProgramFile:
    program: str
    entry: FileControlEntry
    fmt: ProgramFormat


def _variable(label: DatasetLabel) -> bool:
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
    if _variable(dataset.label):
        return VariableRecordDriver(path, mode, record_length)
    return by_organization()


class AllocatedFileIOProvider(RealFileIOProvider):
    """Opens a file as its DD was allocated: DISP=MOD appends; a label the FD contradicts fails with status 39."""

    def __init__(
        self,
        base_dir: Path,
        files: Sequence[ProgramFile],
        env: DdEnvironment,
        relabeller: Relabeller,
    ) -> None:
        super().__init__(base_dir, [f.entry for f in files], dict(env.paths()))
        appended = {name.text for name in env.appended()}
        self._appended_files = frozenset(
            f.entry.file_name for f in files if f.entry.assign_to in appended
        )
        self._files: Mapping[str, ProgramFile] = {f.entry.file_name: f for f in files}
        self._relabeller = relabeller
        self._datasets: Table[str, Dataset] = Table()
        for name, dataset in _datasets(files, env):
            self._datasets.put(name, dataset)
        self._concatenations: Mapping[str, tuple[MemberAllocation, ...]] = dict(
            _concatenations(files, env)
        )

    def _opened_as(self, filename: str, mode: str) -> str:
        if mode == OpenMode.OUTPUT.value and filename in self._appended_files:
            return OpenMode.EXTEND.value
        return mode

    def _supports(self, filename: str, mode: str) -> bool:
        if filename in self._concatenations:
            return mode == OpenMode.INPUT.value
        if self._datasets.has(filename):
            return _supported(self._datasets.get(filename).label, mode)
        return True

    def _admits(self, filename: str, mode: str, key: RecordKey) -> bool:
        if filename in self._concatenations:
            return _concatenation_admitted(
                self._files[filename].fmt, self._concatenations[filename]
            )
        return self._admits_dataset(filename, mode, key)

    def _admits_dataset(self, filename: str, mode: str, key: RecordKey) -> bool:
        if not self._datasets.has(filename):
            return True
        file = self._files[filename]
        if file.entry.organization is FileOrganization.INDEXED:
            dataset = self._datasets.get(filename)
            return _agrees(dataset, indexed_conflicts(file.fmt, key, dataset.label))
        return self._admits_sequential(filename, file.fmt, mode)

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

    def _driver(
        self,
        filename: str,
        org: FileOrganization,
        path: Path,
        mode: OpenMode,
        record_length: int,
        key_offset: int,
        key_length: int,
    ) -> FileOrganizationDriver:
        if filename in self._concatenations:
            members = self._concatenations[filename]
            return ConcatenatedDriver(
                tuple(partial(_member_driver, m, record_length) for m in members)
            )
        by_organization = partial(
            super()._driver,
            filename,
            org,
            path,
            mode,
            record_length,
            key_offset,
            key_length,
        )
        if not self._datasets.has(filename):
            return by_organization()
        return _dataset_driver(
            self._datasets.get(filename), path, mode, record_length, by_organization
        )

    def _open_file(
        self,
        filename: str,
        mode: str,
        record_length: int,
        organization: str,
        key_offset: int,
        key_length: int,
        program: str,
    ) -> IOResult:
        opened = self._opened_as(filename, mode)
        if not self._supports(filename, opened):
            return to_ioresult(AccessResult(AccessCondition.OPEN_MODE_NOT_SUPPORTED))
        if not self._admits(filename, opened, RecordKey(key_offset, key_length)):
            return to_ioresult(AccessResult(AccessCondition.ATTRIBUTE_CONFLICT))
        return super()._open_file(
            filename,
            opened,
            record_length,
            organization,
            key_offset,
            key_length,
            program,
        )


def _datasets(
    files: Sequence[ProgramFile], env: DdEnvironment
) -> tuple[tuple[str, Dataset], ...]:
    allocations = dict(env.entries)
    return tuple(
        (f.entry.file_name, allocation.dataset)
        for f in files
        for ddname, allocation in allocations.items()
        if ddname.text == f.entry.assign_to
        and isinstance(allocation, DatasetAllocation)
    )


def _concatenations(
    files: Sequence[ProgramFile], env: DdEnvironment
) -> tuple[tuple[str, tuple[MemberAllocation, ...]], ...]:
    return tuple(
        (f.entry.file_name, allocation.members)
        for f in files
        for ddname, allocation in env.entries
        if ddname.text == f.entry.assign_to
        and isinstance(allocation, ConcatenatedAllocation)
    )


def _member_label(member: MemberAllocation) -> DatasetLabel:
    match member:
        case DatasetAllocation(dataset=dataset):
            return dataset.label
        case InStreamAllocation():
            return CARDS
        case _:
            return LabelPending()


_UNNAMED_MEMBERS: Mapping[type[MemberAllocation], str] = {
    InStreamAllocation: "DD *",
    DummyAllocation: "DUMMY",
    SysoutAllocation: "SYSOUT",
}


def _member_name(member: MemberAllocation) -> str:
    match member:
        case DatasetAllocation(dataset=dataset):
            return dataset.dsn
        case _:
            return _UNNAMED_MEMBERS[type(member)]


def _named(
    member: MemberAllocation, found: Sequence[LabelConflict]
) -> tuple[tuple[str, LabelConflict], ...]:
    return tuple((_member_name(member), conflict) for conflict in found)


def _concatenation_admitted(
    fmt: ProgramFormat, members: Sequence[MemberAllocation]
) -> bool:
    first, *later = members
    return _logged(
        (
            *_named(first, conflicting(fmt, _member_label(first))),
            *chain.from_iterable(
                _named(member, joining(fmt, _member_label(member))) for member in later
            ),
        )
    )


def _member_driver(
    member: MemberAllocation, record_length: int
) -> FileOrganizationDriver:
    if _variable(_member_label(member)):
        return VariableRecordDriver(member.path(), OpenMode.INPUT, record_length)
    return open_driver(
        FileOrganization.SEQUENTIAL,
        member.path(),
        OpenMode.INPUT,
        record_length,
        0,
        0,
    )
