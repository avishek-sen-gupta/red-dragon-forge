"""The files a program declares, read from its file-definitions Data."""

from cobol_asg.cobol_statements import FileControlEntry
from cobol_asg.ref_mod import RefModOperand
from cobol_asg.file_enums import AccessMode, FileOrganization
from interpreter.cobol.data_literals import boolean, integer, named, text
from interpreter.cobol.file_definitions_data import FILE_DEFINITIONS
from interpreter.data_value import DataList, DataRecord, DataValue
from interpreter.instructions import Data
from interpreter.var_name import VarName
from jackal.cobol_files import ProgramFile
from jackal.file_definitions import program_files_in
from jackal.record_format import FixedFormat, FormatFromDataset, VariableFormat
from tests.covers import NotLanguageFeature, covers


def _fd(
    mode: str, clause: DataRecord, lengths: tuple[int, ...], depending: bool
) -> DataRecord:
    return DataRecord(
        (
            named("recording_mode", text(mode)),
            named("record_clause", clause),
            named("record_lengths", DataList(tuple(integer(n) for n in lengths))),
            named("depending", boolean(depending)),
        )
    )


def _file(
    name: str,
    organization: str,
    access: str,
    record_key: str,
    relative_key: str,
    fds: tuple[DataValue, ...],
) -> DataRecord:
    return DataRecord(
        (
            named("program", text("FILEDEFS")),
            named("file_name", text(name)),
            named("assign_to", text(f"{name[:3]}DD")),
            named("organization", text(organization)),
            named("access_mode", text(access)),
            named("record_key", text(record_key)),
            named("relative_key", text(relative_key)),
            named("file_status", text(f"WS-{name[:3]}")),
            named("fd", DataList(fds)),
        )
    )


def _clause(kind: str, *fields: tuple[str, DataValue]) -> DataRecord:
    return DataRecord((named("kind", text(kind)), *(named(n, v) for n, v in fields)))


_FILES = (
    _file(
        "SEQ-FILE",
        "SEQUENTIAL",
        "SEQUENTIAL",
        "",
        "",
        (
            _fd(
                "V",
                _clause(
                    "varying",
                    ("minimum", integer(10)),
                    ("maximum", integer(50)),
                    ("depending_on", text("WS-LEN")),
                ),
                (50,),
                False,
            ),
        ),
    ),
    _file(
        "IDX-FILE",
        "INDEXED",
        "DYNAMIC",
        "IDX-KEY",
        "",
        (_fd("", _clause("contains", ("size", integer(80))), (80,), False),),
    ),
    _file(
        "REL-FILE",
        "RELATIVE",
        "RANDOM",
        "",
        "WS-RELNO",
        (
            _fd(
                "",
                _clause("range", ("minimum", integer(20)), ("maximum", integer(60))),
                (20, 60),
                False,
            ),
        ),
    ),
    _file(
        "ODO-FILE",
        "SEQUENTIAL",
        "SEQUENTIAL",
        "",
        "",
        (_fd("", _clause("none"), (40,), True),),
    ),
    _file("NOFD-FILE", "SEQUENTIAL", "SEQUENTIAL", "", "", ()),
)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_each_file_record_becomes_its_entry_and_its_fds_format():
    ir = [
        Data(
            name=VarName("__other"),
            value=DataRecord((named("files", DataList(_FILES)),)),
        ),
        Data(
            name=FILE_DEFINITIONS, value=DataRecord((named("files", DataList(_FILES)),))
        ),
    ]

    assert program_files_in(ir) == (
        ProgramFile(
            "FILEDEFS",
            FileControlEntry(
                "SEQ-FILE",
                "SEQDD",
                FileOrganization.SEQUENTIAL,
                AccessMode.SEQUENTIAL,
                RefModOperand(name=""),
                relative_key=RefModOperand(name=""),
                file_status_var=RefModOperand(name="WS-SEQ"),
            ),
            VariableFormat(54),
        ),
        ProgramFile(
            "FILEDEFS",
            FileControlEntry(
                "IDX-FILE",
                "IDXDD",
                FileOrganization.INDEXED,
                AccessMode.DYNAMIC,
                RefModOperand(name="IDX-KEY"),
                relative_key=RefModOperand(name=""),
                file_status_var=RefModOperand(name="WS-IDX"),
            ),
            FixedFormat(80),
        ),
        ProgramFile(
            "FILEDEFS",
            FileControlEntry(
                "REL-FILE",
                "RELDD",
                FileOrganization.RELATIVE,
                AccessMode.RANDOM,
                RefModOperand(name=""),
                relative_key=RefModOperand(name="WS-RELNO"),
                file_status_var=RefModOperand(name="WS-REL"),
            ),
            VariableFormat(64),
        ),
        ProgramFile(
            "FILEDEFS",
            FileControlEntry(
                "ODO-FILE",
                "ODODD",
                FileOrganization.SEQUENTIAL,
                AccessMode.SEQUENTIAL,
                RefModOperand(name=""),
                relative_key=RefModOperand(name=""),
                file_status_var=RefModOperand(name="WS-ODO"),
            ),
            VariableFormat(44),
        ),
        ProgramFile(
            "FILEDEFS",
            FileControlEntry(
                "NOFD-FILE",
                "NOFDD",
                FileOrganization.SEQUENTIAL,
                AccessMode.SEQUENTIAL,
                RefModOperand(name=""),
                relative_key=RefModOperand(name=""),
                file_status_var=RefModOperand(name="WS-NOF"),
            ),
            FormatFromDataset(),
        ),
    )
