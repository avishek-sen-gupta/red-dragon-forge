"""The files a program declares, read from the file-definitions Data in its linked IR."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from cobol_asg.cobol_statements import (
    FileControlEntry,
    FileDescription,
    NoRecordClause,
    RecordClause,
    RecordContains,
    RecordContainsRange,
    RecordVarying,
)
from cobol_asg.file_enums import AccessMode, FileOrganization, RecordingMode
from interpreter.cobol.file_definitions_data import FILE_DEFINITIONS
from interpreter.data_value import DataList, DataRecord, DataScalar, DataValue
from interpreter.field_name import FieldName
from interpreter.instructions import Data, InstructionBase
from interpreter.project.types import LinkedProgram
from jackal.cobol_files import ProgramFile
from jackal.record_format import (
    FdRecords,
    FormatFromDataset,
    ProgramFormat,
    program_format,
)


def _field(record: DataRecord, name: str) -> DataValue:
    found = tuple(f.value for f in record.fields if f.name == FieldName(name))
    match found:
        case (value,):
            return value
        case _:
            raise ValueError(f"file definition has no single field {name}")


def _text(record: DataRecord, name: str) -> str:
    match _field(record, name):
        case DataScalar(value=str() as value):
            return value
        case other:
            raise ValueError(f"file definition field {name} is not text: {other!r}")


def _int(value: DataValue, name: str) -> int:
    match value:
        case DataScalar(value=bool()):
            raise ValueError(f"file definition field {name} is not an integer")
        case DataScalar(value=int() as number):
            return number
        case other:
            raise ValueError(
                f"file definition field {name} is not an integer: {other!r}"
            )


def _bool(record: DataRecord, name: str) -> bool:
    match _field(record, name):
        case DataScalar(value=bool() as value):
            return value
        case other:
            raise ValueError(
                f"file definition field {name} is not a boolean: {other!r}"
            )


def _items(record: DataRecord, name: str) -> tuple[DataValue, ...]:
    match _field(record, name):
        case DataList(items=items):
            return items
        case other:
            raise ValueError(f"file definition field {name} is not a list: {other!r}")


def _record(value: DataValue, name: str) -> DataRecord:
    match value:
        case DataRecord():
            return value
        case other:
            raise ValueError(f"file definition field {name} is not a record: {other!r}")


def _records(record: DataRecord, name: str) -> tuple[DataRecord, ...]:
    return tuple(_record(item, name) for item in _items(record, name))


def _ints(record: DataRecord, name: str) -> tuple[int, ...]:
    return tuple(_int(item, name) for item in _items(record, name))


def _entry(record: DataRecord) -> FileControlEntry:
    return FileControlEntry(
        file_name=_text(record, "file_name"),
        assign_to=_text(record, "assign_to"),
        organization=FileOrganization(_text(record, "organization")),
        access_mode=AccessMode(_text(record, "access_mode")),
        record_key=_text(record, "record_key"),
        relative_key=_text(record, "relative_key"),
        file_status_var=_text(record, "file_status"),
    )


def _contains(record: DataRecord) -> RecordClause:
    return RecordContains(_int(_field(record, "size"), "size"))


def _range(record: DataRecord) -> RecordClause:
    return RecordContainsRange(
        _int(_field(record, "minimum"), "minimum"),
        _int(_field(record, "maximum"), "maximum"),
    )


def _varying(record: DataRecord) -> RecordClause:
    return RecordVarying(
        _int(_field(record, "minimum"), "minimum"),
        _int(_field(record, "maximum"), "maximum"),
        _text(record, "depending_on"),
    )


_CLAUSES: Mapping[str, Callable[[DataRecord], RecordClause]] = {
    "none": lambda _: NoRecordClause(),
    "contains": _contains,
    "range": _range,
    "varying": _varying,
}


def _clause(record: DataRecord) -> RecordClause:
    kind = _text(record, "kind")
    if kind not in _CLAUSES:
        raise ValueError(f"file definition field kind is unknown: {kind}")
    return _CLAUSES[kind](record)


def _format(record: DataRecord) -> ProgramFormat:
    match _records(record, "fd"):
        case (fd,):
            return program_format(
                FileDescription(
                    fd_name=_text(record, "file_name"),
                    recording_mode=RecordingMode(_text(fd, "recording_mode")),
                    record_clause=_clause(
                        _record(_field(fd, "record_clause"), "record_clause")
                    ),
                ),
                FdRecords(_ints(fd, "record_lengths"), _bool(fd, "depending")),
            )
        case _:
            return FormatFromDataset()


def _files(data: Data) -> tuple[ProgramFile, ...]:
    return tuple(
        ProgramFile(_entry(f), _format(f))
        for f in _records(_record(data.value, "files"), "files")
    )


def program_files_in(ir: Sequence[InstructionBase]) -> tuple[ProgramFile, ...]:
    return tuple(
        file
        for i in ir
        if isinstance(i, Data) and i.name == FILE_DEFINITIONS
        for file in _files(i)
    )


def program_files_of(linked: LinkedProgram) -> tuple[ProgramFile, ...]:
    return program_files_in(linked.merged_ir)
