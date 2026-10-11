"""jackal's COBOL file handler: red-dragon's, opening each file as its DD was allocated and its label allows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from cobol_asg.asg_types import CobolASG, CobolField
from cobol_asg.cobol_statements import FileControlEntry
from cobol_asg.file_enums import FileOrganization, OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from interpreter.cobol.data_layout import record_length
from interpreter.cobol.file_drivers import FileOrganizationDriver, open_driver
from interpreter.cobol.io_provider import IOResult
from interpreter.cobol.real_file_provider import RealFileIOProvider, to_ioresult
from jackal.allocation import (
    ConcatenatedAllocation,
    DatasetAllocation,
    DdEnvironment,
    InStreamAllocation,
    MemberAllocation,
)
from jackal.catalog_stores import Table
from jackal.concatenated_records import ConcatenatedDriver
from jackal.dataset import Dataset, Relabeller
from jackal.labels import (
    CARDS,
    VARIABLE,
    DatasetLabel,
    KsdsLabel,
    Label,
    LabelPending,
    SequentialLabel,
)
from jackal.record_format import (
    FdRecords,
    FixedFormat,
    FormatFromDataset,
    ProgramFormat,
    VariableFormat,
    conflicts,
    joins,
    label_for,
    program_format,
)
from jackal.variable_records import VariableRecordDriver

_LABELLING = frozenset({OpenMode.OUTPUT.value, OpenMode.EXTEND.value})


@dataclass(frozen=True)
class ProgramFile:
    entry: FileControlEntry
    fmt: ProgramFormat


def _depends(f: CobolField) -> bool:
    return bool(f.occurs_depending_on) or any(_depends(c) for c in f.children)


def _records(asg: CobolASG, fd_name: str) -> FdRecords:
    roots = tuple(
        f
        for f in asg.file_fields
        if f.level == 1 and asg.file_record_to_select.get(f.name.upper()) == fd_name
    )
    return FdRecords(
        tuple(record_length(f) for f in roots), any(_depends(f) for f in roots)
    )


def _format(asg: CobolASG, entry: FileControlEntry) -> ProgramFormat:
    fds = {d.fd_name.upper(): d for d in asg.file_descriptions}
    name = entry.file_name.upper()
    if name not in fds:
        return FormatFromDataset()
    return program_format(fds[name], _records(asg, name))


def program_files(asg: CobolASG) -> tuple[ProgramFile, ...]:
    return tuple(ProgramFile(e, _format(asg, e)) for e in asg.file_control)


def _variable(label: DatasetLabel) -> bool:
    match label:
        case SequentialLabel():
            return label.recfm in VARIABLE
        case _:
            return False


def _indexed_conflict(label: DatasetLabel) -> bool:
    match label:
        case KsdsLabel():
            return False
        case _:
            return True


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

    def _admits(self, filename: str, mode: str) -> bool:
        if filename in self._concatenations:
            return _concatenation_admitted(
                self._files[filename].fmt, self._concatenations[filename]
            )
        return self._admits_dataset(filename, mode)

    def _admits_dataset(self, filename: str, mode: str) -> bool:
        if not self._datasets.has(filename):
            return True
        file = self._files[filename]
        if file.entry.organization is FileOrganization.INDEXED:
            return not _indexed_conflict(self._datasets.get(filename).label)
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
                return not conflicts(fmt, dataset.label)

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
        if self._datasets.has(filename) and _variable(
            self._datasets.get(filename).label
        ):
            return VariableRecordDriver(path, mode, record_length)
        return super()._driver(
            filename,
            org,
            path,
            mode,
            record_length,
            key_offset,
            key_length,
        )

    def _open_file(
        self,
        filename: str,
        mode: str,
        record_length: int,
        organization: str,
        key_offset: int,
        key_length: int,
    ) -> IOResult:
        opened = self._opened_as(filename, mode)
        if filename in self._concatenations and opened != OpenMode.INPUT.value:
            return to_ioresult(AccessResult(AccessCondition.OPEN_MODE_NOT_SUPPORTED))
        if not self._admits(filename, opened):
            return to_ioresult(AccessResult(AccessCondition.ATTRIBUTE_CONFLICT))
        return super()._open_file(
            filename, opened, record_length, organization, key_offset, key_length
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


def _concatenation_admitted(
    fmt: ProgramFormat, members: Sequence[MemberAllocation]
) -> bool:
    first, *later = (_member_label(m) for m in members)
    return not conflicts(fmt, first) and all(joins(fmt, label) for label in later)


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
