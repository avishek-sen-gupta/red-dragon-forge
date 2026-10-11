"""The record format a COBOL FD asks for, by Enterprise COBOL's rules, and its fit with a dataset's label."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from cobol_asg.cobol_statements import (
    FileDescription,
    NoRecordClause,
    RecordClause,
    RecordContains,
    RecordContainsRange,
    RecordVarying,
)
from cobol_asg.file_enums import RecordingMode
from jackal.labels import (
    VARIABLE,
    DatasetLabel,
    LabelPending,
    RecordFormat,
    SequentialLabel,
)

_RDW = 4


@dataclass(frozen=True)
class FdRecords:
    lengths: tuple[int, ...]
    depending: bool


@dataclass(frozen=True)
class FixedFormat:
    lrecl: int


@dataclass(frozen=True)
class VariableFormat:
    lrecl: int


@dataclass(frozen=True)
class FormatFromDataset:
    """RECORD CONTAINS 0: the program takes its record length from the dataset."""


ProgramFormat: TypeAlias = FixedFormat | VariableFormat | FormatFromDataset


class UnsupportedRecordingMode(Exception):
    """RECORDING MODE U or S: one record per block, or spanned records; jackal does not model blocks."""


def _largest(clause: RecordClause, records: FdRecords) -> int:
    match clause:
        case RecordContains():
            return clause.size
        case _:
            return _upper_bound(clause, records)


def _upper_bound(
    clause: RecordContainsRange | RecordVarying | NoRecordClause, records: FdRecords
) -> int:
    match clause:
        case RecordContainsRange() | RecordVarying() if clause.maximum:
            return clause.maximum
        case _:
            return max(records.lengths)


def _varies(clause: RecordClause, records: FdRecords) -> bool:
    match clause:
        case NoRecordClause():
            return records.depending or len(set(records.lengths)) > 1
        case _:
            return _clause_varies(clause)


def _clause_varies(
    clause: RecordContains | RecordContainsRange | RecordVarying,
) -> bool:
    match clause:
        case RecordContainsRange():
            return clause.minimum != clause.maximum
        case _:
            return isinstance(clause, RecordVarying)


def _sized(variable: bool, largest: int) -> ProgramFormat:
    if not largest:
        return FormatFromDataset()
    return VariableFormat(largest + _RDW) if variable else FixedFormat(largest)


_CODED: dict[RecordingMode, bool] = {RecordingMode.F: False, RecordingMode.V: True}


def _derived(fd: FileDescription, records: FdRecords) -> bool:
    if fd.recording_mode in _CODED:
        return _CODED[fd.recording_mode]
    if fd.recording_mode is RecordingMode.NOT_CODED:
        return _varies(fd.record_clause, records)
    raise UnsupportedRecordingMode(
        f"FD {fd.fd_name} has RECORDING MODE {fd.recording_mode.value}; "
        "jackal does not model blocks"
    )


def program_format(fd: FileDescription, records: FdRecords) -> ProgramFormat:
    return _sized(_derived(fd, records), _largest(fd.record_clause, records))


def _sequential_conflict(
    fmt: FixedFormat | VariableFormat, label: SequentialLabel
) -> bool:
    variable = isinstance(fmt, VariableFormat)
    return (label.recfm in VARIABLE) != variable or label.lrecl != fmt.lrecl


def conflicts(fmt: ProgramFormat, label: DatasetLabel) -> bool:
    match (fmt, label):
        case (FormatFromDataset(), _) | (_, LabelPending()):
            return False
        case (FixedFormat() | VariableFormat(), SequentialLabel()):
            return _sequential_conflict(fmt, label)
        case _:
            return True


def label_for(fmt: FixedFormat | VariableFormat) -> SequentialLabel:
    match fmt:
        case FixedFormat():
            return SequentialLabel(RecordFormat.F, fmt.lrecl)
        case VariableFormat():
            return SequentialLabel(RecordFormat.V, fmt.lrecl)
