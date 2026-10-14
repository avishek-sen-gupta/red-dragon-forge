"""Unit tests for the VsamEngine CICS adapter over cataloged clusters and paths.

Each CICS file is a cluster or path in a test system catalog; the engine opens
its file per operation. Assertions are on the CICS surface (records returned,
EIBRESP, browse order) — there is no in-memory store.
"""

from pathlib import Path

from tests.covers import covers, NotLanguageFeature
from cics.vsam.no_record import NoRecord
from cics.vsam.record_read import RecordRead
from cics.vsam.engine import VsamEngine
from cics.vsam.eibresp import (
    RESP_DISABLED,
    RESP_NORMAL,
    RESP_NOTFND,
    RESP_DUPREC,
    RESP_ENDFILE,
)
from cics.vsam.browse import BrowseStart
from cics.vsam.file_table import cics_files
from catnip.dataset import Dataset
from tests.vsam_system import SeedAix, SeedCluster, build_test_system

REC_LEN = 10
KEY_LEN = 4


def _rec(key: str, rest: str = "") -> bytes:
    body = rest.ljust(REC_LEN - KEY_LEN)[: REC_LEN - KEY_LEN]
    return (key.ljust(KEY_LEN)[:KEY_LEN] + body).encode()


def _engine_with_records(
    tmp_path: Path, records: list[bytes], rec_len: int = REC_LEN
) -> VsamEngine:
    clusters = (SeedCluster("TESTDS", rec_len, KEY_LEN, tuple(records)),)
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_read_on_an_empty_cluster_is_notfnd(tmp_path: Path) -> None:
    engine = _engine_with_records(tmp_path, [])
    assert engine.read("TESTDS", b"AA01", KEY_LEN) == NoRecord(RESP_NOTFND)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_cics_file_the_table_does_not_define_is_disabled_for_every_operation(
    tmp_path: Path,
) -> None:
    engine = _engine_with_records(tmp_path, [_rec("AA01", "DATA")])
    record = _rec("BB02", "NEW")

    assert (
        engine.read("NOFILE", b"AA01", KEY_LEN),
        engine.write("NOFILE", b"BB02", KEY_LEN, record),
        engine.rewrite("NOFILE", b"AA01", KEY_LEN, record),
        engine.delete("NOFILE", b"AA01", KEY_LEN),
        engine.startbr("NOFILE", b"AA01", KEY_LEN, ("T", "NOFILE", "0")),
    ) == (
        NoRecord(RESP_DISABLED),
        RESP_DISABLED,
        RESP_DISABLED,
        RESP_DISABLED,
        RESP_DISABLED,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_existing_record(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "DATA")])
    record_read = engine.read("TESTDS", b"AA01", KEY_LEN)
    assert isinstance(record_read, RecordRead)
    record, resp = record_read.record, record_read.resp
    assert resp == RESP_NORMAL
    assert record is not None and record[:KEY_LEN] == b"AA01"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_not_found(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "DATA")])
    resp = engine.read("TESTDS", b"ZZ99", KEY_LEN).resp
    assert resp == RESP_NOTFND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_write_new_record(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [])
    assert engine.write("TESTDS", b"AA01", KEY_LEN, _rec("AA01", "NEW")) == RESP_NORMAL
    resp2 = engine.read("TESTDS", b"AA01", KEY_LEN).resp
    assert resp2 == RESP_NORMAL


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_write_duplicate_returns_duprec(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "OLD")])
    assert engine.write("TESTDS", b"AA01", KEY_LEN, _rec("AA01", "NEW")) == RESP_DUPREC


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_rewrite_updates_record(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "OLD")])
    assert (
        engine.rewrite("TESTDS", b"AA01", KEY_LEN, _rec("AA01", "UPD")) == RESP_NORMAL
    )
    record_read = engine.read("TESTDS", b"AA01", KEY_LEN)
    assert isinstance(record_read, RecordRead)
    record = record_read.record
    assert b"UPD" in record


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_rewrite_without_key_extracts_key_from_record(tmp_path: Path):
    """EXEC CICS REWRITE supplies FROM but no RIDFLD — the key must be taken
    from the FROM record itself (its key field), not from the passed key arg
    (which the lowering leaves empty). (CardDemo COACTUPC 9600-WRITE-PROCESSING.)"""
    engine = _engine_with_records(tmp_path, [_rec("AA01", "OLD")])
    assert engine.rewrite("TESTDS", b"", KEY_LEN, _rec("AA01", "UPD")) == RESP_NORMAL
    record_read = engine.read("TESTDS", b"AA01", KEY_LEN)
    assert isinstance(record_read, RecordRead)
    record = record_read.record
    assert b"UPD" in record


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_removes_record(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "DATA")])
    assert engine.delete("TESTDS", b"AA01", KEY_LEN) == RESP_NORMAL
    resp2 = engine.read("TESTDS", b"AA01", KEY_LEN).resp
    assert resp2 == RESP_NOTFND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_keyless_delete_uses_last_read_record(tmp_path: Path):
    """EXEC CICS DELETE without RIDFLD deletes the record most recently READ
    (read-for-update semantics). An empty key falls back to the held key."""
    engine = _engine_with_records(
        tmp_path, [_rec("AA01", "AAAA"), _rec("BB02", "BBBB")]
    )
    # Read BB02 for update, then a keyless DELETE removes exactly that record.
    rec_read = engine.read("TESTDS", b"BB02", KEY_LEN)
    assert isinstance(rec_read, RecordRead)
    rec, resp = rec_read.record, rec_read.resp
    assert resp == RESP_NORMAL and rec is not None
    assert engine.delete("TESTDS", b"", KEY_LEN) == RESP_NORMAL
    gone = engine.read("TESTDS", b"BB02", KEY_LEN).resp
    assert gone == RESP_NOTFND
    # The other record is untouched.
    other = engine.read("TESTDS", b"AA01", KEY_LEN).resp
    assert other == RESP_NORMAL


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_keyless_delete_without_prior_read_is_notfnd(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "AAAA")])
    assert engine.delete("TESTDS", b"", KEY_LEN) == RESP_NOTFND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_browse_forward(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01"), _rec("BB02"), _rec("CC03")])
    cursor = ("task0", "TESTDS", "cur0")
    engine.startbr("TESTDS", b"AA01", KEY_LEN, cursor)
    rec1_read = engine.readnext("TESTDS", cursor)
    assert isinstance(rec1_read, RecordRead)
    rec1, r1 = rec1_read.record, rec1_read.resp
    rec2_read = engine.readnext("TESTDS", cursor)
    assert isinstance(rec2_read, RecordRead)
    rec2, r2 = rec2_read.record, rec2_read.resp
    r3 = engine.readnext("TESTDS", cursor).resp
    r4 = engine.readnext("TESTDS", cursor).resp
    assert r1 == RESP_NORMAL and rec1[:4] == b"AA01"
    assert r2 == RESP_NORMAL and rec2[:4] == b"BB02"
    assert r3 == RESP_NORMAL
    assert r4 == RESP_ENDFILE
    engine.endbr("TESTDS", cursor)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_browse_reverse(tmp_path: Path):
    """READNEXT then READPREV: the direction switch re-reads the last record read
    (CICS semantics), then a further READPREV walks back to the prior record."""
    engine = _engine_with_records(tmp_path, [_rec("AA01"), _rec("BB02")])
    cursor = ("task0", "TESTDS", "cur0")
    engine.startbr("TESTDS", b"BB02", KEY_LEN, cursor)
    nxt_read = engine.readnext("TESTDS", cursor)
    assert isinstance(nxt_read, RecordRead)
    nxt = nxt_read.record
    assert nxt[:4] == b"BB02"
    # Reversal re-reads the just-read record.
    rev1_read = engine.readprev("TESTDS", cursor)
    assert isinstance(rev1_read, RecordRead)
    rev1, r1 = rev1_read.record, rev1_read.resp
    assert r1 == RESP_NORMAL and rev1[:4] == b"BB02"
    # Continue backward to the prior record.
    rev2_read = engine.readprev("TESTDS", cursor)
    assert isinstance(rev2_read, RecordRead)
    rev2, r2 = rev2_read.record, rev2_read.resp
    assert r2 == RESP_NORMAL and rev2[:4] == b"AA01"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_startbr_high_values_then_readprev_returns_last_record(tmp_path: Path):
    """CardDemo COTRN02C id-generation idiom: MOVE HIGH-VALUES TO key, STARTBR,
    then READPREV (no intervening READNEXT) must return the LAST (highest-key)
    record so the program can derive the next id. The STARTBR positions past
    end-of-file; the first READPREV walks back to the final record."""
    engine = _engine_with_records(tmp_path, [_rec("AA01"), _rec("BB02"), _rec("CC03")])
    cursor = ("task0", "TESTDS", "cur0")
    high = b"\xff" * KEY_LEN
    assert engine.startbr("TESTDS", high, KEY_LEN, cursor) == RESP_NORMAL
    rec_read = engine.readprev("TESTDS", cursor)
    assert isinstance(rec_read, RecordRead)
    rec, resp = rec_read.record, rec_read.resp
    assert resp == RESP_NORMAL, f"first READPREV after STARTBR(HIGH) gave resp {resp}"
    assert rec[:4] == b"CC03", f"expected last record CC03, got {rec[:4]!r}"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_startbr_then_readprev_walks_backwards_to_first(tmp_path: Path):
    """A fresh STARTBR(HIGH) then repeated READPREV walks every record in
    descending key order, ending at ENDFILE past the first record."""
    engine = _engine_with_records(tmp_path, [_rec("AA01"), _rec("BB02"), _rec("CC03")])
    cursor = ("task0", "TESTDS", "cur0")
    engine.startbr("TESTDS", b"\xff" * KEY_LEN, KEY_LEN, cursor)
    r1_read = engine.readprev("TESTDS", cursor)
    assert isinstance(r1_read, RecordRead)
    r1, p1 = r1_read.record, r1_read.resp
    r2_read = engine.readprev("TESTDS", cursor)
    assert isinstance(r2_read, RecordRead)
    r2, p2 = r2_read.record, r2_read.resp
    r3_read = engine.readprev("TESTDS", cursor)
    assert isinstance(r3_read, RecordRead)
    r3, p3 = r3_read.record, r3_read.resp
    p4 = engine.readprev("TESTDS", cursor).resp
    assert (p1, r1[:4]) == (RESP_NORMAL, b"CC03")
    assert (p2, r2[:4]) == (RESP_NORMAL, b"BB02")
    assert (p3, r3[:4]) == (RESP_NORMAL, b"AA01")
    assert p4 == RESP_ENDFILE


def _engine_offset(
    tmp_path: Path, records: list[bytes], rec_len: int, key_offset: int, key_length: int
) -> VsamEngine:
    clusters = (
        SeedCluster(
            "OFFBASE",
            rec_len,
            16,
            tuple(records),
            aix=(SeedAix("OFFDS", key_offset, key_length, False),),
        ),
    )
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_matches_key_at_nonzero_offset(tmp_path: Path):
    rec = b"C" * 16 + b"000000001" + b"00000000011" + b"\x00" * 4
    engine = _engine_offset(tmp_path, [rec], len(rec), key_offset=25, key_length=11)
    record_read = engine.read("OFFDS", b"00000000011", 11)
    assert isinstance(record_read, RecordRead)
    record, resp = record_read.record, record_read.resp
    assert resp == RESP_NORMAL
    assert record is not None
    assert record[25:36] == b"00000000011"
    assert record[16:25] == b"000000001"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_offset_nonmatching_key_notfnd(tmp_path: Path):
    rec = b"C" * 16 + b"000000001" + b"00000000011" + b"\x00" * 4
    engine = _engine_offset(tmp_path, [rec], len(rec), key_offset=25, key_length=11)
    resp = engine.read("OFFDS", b"99999999999", 11).resp
    assert resp == RESP_NOTFND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_default_offset_zero_unchanged(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "DATA")])
    record_read = engine.read("TESTDS", b"AA01", KEY_LEN)
    assert isinstance(record_read, RecordRead)
    record, resp = record_read.record, record_read.resp
    assert resp == RESP_NORMAL
    assert record is not None and record[:KEY_LEN] == b"AA01"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_write_lands_on_backing_file_and_survives_new_engine(tmp_path: Path) -> None:
    """A WRITE goes straight to the cluster's file (the file IS the store); a
    fresh engine over the same system catalog reads it back."""
    system, dsnames = build_test_system(
        tmp_path, (SeedCluster("DS", 4, 4, (b"AAAA",)),)
    )
    eng = VsamEngine(cics_files(system, dsnames))
    assert eng.write("DS", b"ZZZZ", 4, b"ZZZZ") == RESP_NORMAL

    from cics.vsam.format import read_flat_file

    cluster = system.lookup("TEST.DS")
    assert isinstance(cluster, Dataset)
    assert read_flat_file(cluster.path, 4) == [b"AAAA", b"ZZZZ"]

    eng2 = VsamEngine(cics_files(system, dsnames))
    rec_read = eng2.read("DS", b"ZZZZ", 4)
    assert isinstance(rec_read, RecordRead)
    rec, resp = rec_read.record, rec_read.resp
    assert resp == RESP_NORMAL and rec == b"ZZZZ"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_startbr_equal_on_absent_key_is_notfnd(tmp_path: Path) -> None:
    engine = _engine_with_records(tmp_path, [_rec("AA01"), _rec("CC03")])
    cursor = ("task0", "TESTDS", "cur0")
    resp = engine.startbr("TESTDS", b"BB02", KEY_LEN, cursor, start=BrowseStart.EQUAL)
    assert resp == RESP_NOTFND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_startbr_equal_positions_on_the_matching_record(tmp_path: Path) -> None:
    engine = _engine_with_records(tmp_path, [_rec("AA01"), _rec("BB02")])
    cursor = ("task0", "TESTDS", "cur0")
    engine.startbr("TESTDS", b"BB02", KEY_LEN, cursor, start=BrowseStart.EQUAL)
    rec_read = engine.readnext("TESTDS", cursor)
    assert isinstance(rec_read, RecordRead)
    rec, resp = rec_read.record, rec_read.resp
    assert (resp, rec[:4]) == (RESP_NORMAL, b"BB02")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_startbr_defaults_to_gteq(tmp_path: Path) -> None:
    engine = _engine_with_records(tmp_path, [_rec("AA01"), _rec("CC03")])
    cursor = ("task0", "TESTDS", "cur0")
    assert engine.startbr("TESTDS", b"BB02", KEY_LEN, cursor) == RESP_NORMAL
    rec_read = engine.readnext("TESTDS", cursor)
    assert isinstance(rec_read, RecordRead)
    rec = rec_read.record
    assert rec[:4] == b"CC03"
