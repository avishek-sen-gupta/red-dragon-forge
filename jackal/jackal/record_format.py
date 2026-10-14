"""The record format a COBOL FD asks for, by Enterprise COBOL's rules, and its fit with a dataset's label."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

from catnip.labels import (
    VARIABLE,
    DatasetLabel,
    KsdsLabel,
    LabelPending,
    PathView,
    RecordFormat,
    SequentialLabel,
)
from cobol_asg.cobol_statements import (
    FileDescription,
    NoRecordClause,
    RecordClause,
    RecordContains,
    RecordContainsRange,
    RecordVarying,
)
from cobol_asg.file_enums import RecordingMode
from jackal.label_conflict import LabelConflict
from jackal.label_field import LabelField
from jackal.record_key import RecordKey

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


def _recfm(fmt: FixedFormat | VariableFormat) -> str:
    return "V" if isinstance(fmt, VariableFormat) else "F"


def _differs(
    field: LabelField, declared: str | int, program: str | int
) -> tuple[LabelConflict, ...]:
    if declared == program:
        return ()
    return (LabelConflict(field, declared, program),)


def _sequential_conflicts(
    fmt: FixedFormat | VariableFormat, label: SequentialLabel
) -> tuple[LabelConflict, ...]:
    declared = "V" if label.recfm in VARIABLE else "F"
    return (
        *_differs(LabelField.RECFM, declared, _recfm(fmt)),
        *_differs(LabelField.LRECL, label.lrecl, fmt.lrecl),
    )


_KINDS: Mapping[type[DatasetLabel], str] = {
    SequentialLabel: "sequential",
    KsdsLabel: "KSDS",
    PathView: "path",
    LabelPending: "pending",
}


def _kind(label: DatasetLabel) -> str:
    return _KINDS[type(label)]


def conflicting(fmt: ProgramFormat, label: DatasetLabel) -> tuple[LabelConflict, ...]:
    match (fmt, label):
        case (FormatFromDataset(), _) | (_, LabelPending()):
            return ()
        case (FixedFormat() | VariableFormat(), SequentialLabel()):
            return _sequential_conflicts(fmt, label)
        case _:
            return (LabelConflict(LabelField.ORGANIZATION, _kind(label), "sequential"),)


def conflicts(fmt: ProgramFormat, label: DatasetLabel) -> bool:
    return bool(conflicting(fmt, label))


def _largest_record(fmt: FixedFormat | VariableFormat) -> int:
    return fmt.lrecl - _RDW if isinstance(fmt, VariableFormat) else fmt.lrecl


def _record_length(fmt: ProgramFormat, lrecl: int) -> tuple[LabelConflict, ...]:
    match fmt:
        case FormatFromDataset():
            return ()
        case _:
            return _differs(LabelField.LRECL, lrecl, _largest_record(fmt))


def _keyed(
    fmt: ProgramFormat, key: RecordKey, lrecl: int, declared: RecordKey
) -> tuple[LabelConflict, ...]:
    return (
        *_record_length(fmt, lrecl),
        *_differs(LabelField.KEY_OFFSET, declared.offset, key.offset),
        *_differs(LabelField.KEY_LENGTH, declared.length, key.length),
    )


def indexed_conflicts(
    fmt: ProgramFormat, key: RecordKey, label: DatasetLabel
) -> tuple[LabelConflict, ...]:
    match label:
        case KsdsLabel():
            return _keyed(
                fmt, key, label.lrecl, RecordKey(label.key_offset, label.key_length)
            )
        case PathView():
            return _keyed(
                fmt,
                key,
                label.base.lrecl,
                RecordKey(label.key_offset, label.key_length),
            )
        case _:
            return (LabelConflict(LabelField.ORGANIZATION, _kind(label), "INDEXED"),)


def label_for(fmt: FixedFormat | VariableFormat) -> SequentialLabel:
    match fmt:
        case FixedFormat():
            return SequentialLabel(RecordFormat.F, fmt.lrecl)
        case VariableFormat():
            return SequentialLabel(RecordFormat.V, fmt.lrecl)


def _shorter_variable(fmt: VariableFormat, label: DatasetLabel) -> bool:
    match label:
        case SequentialLabel() if label.recfm in VARIABLE:
            return label.lrecl < fmt.lrecl
        case _:
            return False


def joining(fmt: ProgramFormat, label: DatasetLabel) -> tuple[LabelConflict, ...]:
    """A later member of a like concatenation: as the first, or a shorter variable LRECL."""
    match fmt:
        case VariableFormat() if _shorter_variable(fmt, label):
            return ()
        case _:
            return conflicting(fmt, label)


def joins(fmt: ProgramFormat, label: DatasetLabel) -> bool:
    return not joining(fmt, label)
