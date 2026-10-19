"""Variable-length records on disk behind a record descriptor word.

Sources: z/OS 3.1 DFSMS Using Data Sets, "Record descriptor word (RDW)", p. 287;
Enterprise COBOL 6.4 Programming Guide, "Updating QSAM files"; Language
Reference 6.4, Table 34 (file status 44). See
docs/records/design/2026-10-12-jackal-variable-records.md.
"""

from catnip.variable_records import VariableRecordDriver
from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition
from tests.covers import NotLanguageFeature, covers


def _drained(path, area):
    drv = VariableRecordDriver(path, OpenMode.INPUT, area)
    reads = tuple(drv.read_seq() for _ in range(4))
    drv.close()
    return tuple((r.condition, r.data) for r in reads)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_records_are_framed_by_an_rdw_and_read_back_at_their_own_length(tmp_path):
    path = tmp_path / "v.dat"
    out = VariableRecordDriver(path, OpenMode.OUTPUT, 0)
    written = (out.write(b"ABC"), out.key_of_reference(1), out.write(b"LONGER"))
    out.close()
    extend = VariableRecordDriver(path, OpenMode.EXTEND, 0)
    extend.write(b"Z")
    extend.close()
    ok, eof = AccessCondition.OK, AccessCondition.END_OF_FILE
    assert (
        tuple(w.condition for w in written),
        path.read_bytes(),
        _drained(path, 0),
        _drained(path, 6)[0],
    ) == (
        (ok, ok, ok),
        b"\x00\x07\x00\x00ABC\x00\x0a\x00\x00LONGER\x00\x05\x00\x00Z",
        ((ok, b"ABC"), (ok, b"LONGER"), (ok, b"Z"), (eof, None)),
        (ok, b"ABC   "),
    )


def _written(path, records):
    out = VariableRecordDriver(path, OpenMode.OUTPUT, 0)
    for record in records:
        out.write(record)
    out.close()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_rewrite_replaces_the_record_just_read_only_at_the_same_length(tmp_path):
    path = tmp_path / "v.dat"
    _written(path, (b"ONE", b"TWO", b"END"))
    io = VariableRecordDriver(path, OpenMode.IO, 0)
    io.read_seq()
    io.read_seq()
    results = (io.rewrite(b"2!2"), io.rewrite(b"LONGER"), io.read_seq().data)
    io.close()
    assert (tuple(r.condition for r in results[:2]), results[2], path.read_bytes()) == (
        (AccessCondition.OK, AccessCondition.BOUNDARY_VIOLATION),
        b"END",
        b"\x00\x07\x00\x00ONE\x00\x07\x00\x002!2\x00\x07\x00\x00END",
    )
