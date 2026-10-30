"""jackal's COBOL file handler: zos's dataset handler, bound by a step's DDs and reading concatenations too."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from functools import partial
from itertools import chain
from pathlib import Path

from catnip.dataset import Relabeller
from catnip.labels import CARDS, DatasetLabel, LabelPending
from catnip.variable_records import VariableRecordDriver
from cobol_asg.file_enums import FileOrganization, OpenMode
from infrastructure.zos.access_methods.file_drivers import (
    FileOrganizationDriver,
    open_driver,
)
from infrastructure.zos.access_methods.prime_key import PrimeKey
from infrastructure.zos.access_methods.record_shape import RecordShape
from interpreter.record_io.file_frame import FileFrame
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
from zos.cobol.io.dataset_files import DatasetFileIOProvider, variable
from zos.cobol.io.file_bindings import FileBindings
from zos.cobol.io.label_conflict import LabelConflict
from zos.cobol.io.program_file import ProgramFile
from zos.cobol.io.record_format import ProgramFormat, conflicting, joining
from zos.cobol.io.record_key import RecordKey

logger = logging.getLogger(__name__)


def _logged(found: Sequence[tuple[str, LabelConflict]]) -> bool:
    for name, conflict in found:
        logger.warning("%s", conflict.described(name))
    return not found


def bindings_of(env: DdEnvironment) -> FileBindings:
    return FileBindings(
        paths=env.paths(),
        appended=frozenset(name.text for name in env.appended()),
        datasets={
            ddname.text: allocation.dataset
            for ddname, allocation in env.entries
            if isinstance(allocation, DatasetAllocation)
        },
    )


class AllocatedFileIOProvider(DatasetFileIOProvider):
    """Opens a file as its DD was allocated: DISP=MOD appends; a label the FD contradicts fails with status 39; a concatenation reads its members in turn."""

    def __init__(
        self,
        base_dir: Path,
        files: Sequence[ProgramFile],
        env: DdEnvironment,
        relabeller: Relabeller,
    ) -> None:
        super().__init__(base_dir, files, bindings_of(env), relabeller)
        self._concatenations: Mapping[str, tuple[MemberAllocation, ...]] = dict(
            _concatenations(files, env)
        )

    def _supports(self, filename: str, mode: str) -> bool:
        if filename in self._concatenations:
            return mode == OpenMode.INPUT.value
        return super()._supports(filename, mode)

    def _admits(self, filename: str, mode: str, prime: RecordKey) -> bool:
        if filename in self._concatenations:
            return _concatenation_admitted(
                self._program_files[filename].fmt, self._concatenations[filename]
            )
        return super()._admits(filename, mode, prime)

    def _driver_for(
        self, frame: FileFrame, path: Path, mode: OpenMode
    ) -> FileOrganizationDriver:
        filename = frame.file_name
        if filename in self._concatenations:
            members = self._concatenations[filename]
            return ConcatenatedDriver(
                tuple(partial(_member_driver, m, frame.record_length) for m in members)
            )
        return super()._driver_for(frame, path, mode)


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
    if variable(_member_label(member)):
        return VariableRecordDriver(member.path(), OpenMode.INPUT, record_length)
    return open_driver(
        member.path(),
        OpenMode.INPUT,
        RecordShape(FileOrganization.SEQUENTIAL, record_length, PrimeKey()),
    )
