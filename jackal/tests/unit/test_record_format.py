"""IBM Enterprise COBOL's record format for an FD, and its fit with a dataset's label.

Sources (z/OS 3.1 era): Enterprise COBOL 6.4 Language Reference, RECORDING MODE
clause; Programming Guide 6.4, ch. 9, Table 21. See
docs/records/design/2026-10-11-jackal-dataset-decisions.md.
"""

import pytest
from catnip.labels import KsdsLabel, RecordFormat, SequentialLabel
from cobol_asg.cobol_statements import (
    FileDescription,
    NoRecordClause,
    RecordContains,
    RecordContainsRange,
    RecordVarying,
)
from cobol_asg.file_enums import RecordingMode
from jackal.record_format import (
    FdRecords,
    FixedFormat,
    FormatFromDataset,
    UnsupportedRecordingMode,
    VariableFormat,
    conflicts,
    joins,
    label_for,
    program_format,
)
from tests.covers import NotLanguageFeature, covers


def _fd(mode: RecordingMode, clause) -> FileDescription:
    return FileDescription("F", mode, clause)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_fd_asks_for_the_record_format_enterprise_cobol_derives():
    nc = RecordingMode.NOT_CODED
    same, mixed = FdRecords((80, 80), False), FdRecords((10, 50), False)
    depending = FdRecords((80,), True)
    assert [
        program_format(_fd(RecordingMode.F, NoRecordClause()), mixed),
        program_format(_fd(RecordingMode.V, NoRecordClause()), same),
        program_format(_fd(nc, RecordContains(120)), mixed),
        program_format(_fd(nc, RecordContains(0)), same),
        program_format(_fd(nc, RecordContainsRange(10, 50)), mixed),
        program_format(_fd(nc, RecordContainsRange(50, 50)), mixed),
        program_format(_fd(nc, RecordVarying(4, 100, "")), mixed),
        program_format(_fd(nc, RecordVarying(0, 0, "")), mixed),
        program_format(_fd(nc, NoRecordClause()), same),
        program_format(_fd(nc, NoRecordClause()), mixed),
        program_format(_fd(nc, NoRecordClause()), depending),
    ] == [
        FixedFormat(50),
        VariableFormat(84),
        FixedFormat(120),
        FormatFromDataset(),
        VariableFormat(54),
        FixedFormat(50),
        VariableFormat(104),
        VariableFormat(54),
        FixedFormat(80),
        VariableFormat(54),
        VariableFormat(84),
    ]
    with pytest.raises(UnsupportedRecordingMode, match="U"):
        program_format(_fd(RecordingMode.U, NoRecordClause()), same)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_format_fits_a_label_of_the_same_kind_and_length_and_writes_one():
    fb80, vb104 = SequentialLabel(RecordFormat.FB, 80), SequentialLabel(
        RecordFormat.VB, 104
    )
    assert [
        conflicts(FixedFormat(80), fb80),
        conflicts(FixedFormat(80), SequentialLabel(RecordFormat.F, 80)),
        conflicts(FixedFormat(50), fb80),
        conflicts(VariableFormat(104), vb104),
        conflicts(VariableFormat(104), fb80),
        conflicts(FixedFormat(104), vb104),
        conflicts(FormatFromDataset(), vb104),
        conflicts(FixedFormat(300), KsdsLabel(300, 0, 11)),
        label_for(FixedFormat(80)),
        label_for(VariableFormat(104)),
    ] == [
        False,
        False,
        True,
        False,
        True,
        True,
        False,
        True,
        SequentialLabel(RecordFormat.F, 80),
        SequentialLabel(RecordFormat.V, 104),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_later_member_joins_a_like_concatenation_as_the_first_or_shorter_variable():
    """z/OS 3.1 JCL Reference, "Logical record lengths for concatenated data sets":
    format-V members may differ in LRECL when the largest comes first."""
    v104, v50 = SequentialLabel(RecordFormat.VB, 104), SequentialLabel(
        RecordFormat.V, 50
    )
    assert [
        joins(VariableFormat(104), v104),
        joins(VariableFormat(104), v50),
        joins(VariableFormat(104), SequentialLabel(RecordFormat.V, 200)),
        joins(FixedFormat(80), SequentialLabel(RecordFormat.F, 40)),
        joins(FixedFormat(80), SequentialLabel(RecordFormat.FB, 80)),
        joins(VariableFormat(104), SequentialLabel(RecordFormat.F, 50)),
    ] == [True, True, False, False, True, False]
