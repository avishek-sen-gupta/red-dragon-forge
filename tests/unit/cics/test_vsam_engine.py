"""Unit tests for the VsamEngine CICS adapter over the file-resident drivers.

Seeding writes backing ``<NAME>.dat`` files (key-sorted for base KSDS) via
``seed_records``; the engine opens them. Assertions are on the CICS surface
(records returned, EIBRESP, browse order) — there is no in-memory store.
"""

from pathlib import Path

from tests.covers import covers, NotLanguageFeature
from cics.vsam.engine import (
    VsamEngine,
    RESP_NORMAL,
    RESP_NOTFND,
    RESP_DUPREC,
    RESP_ENDFILE,
)
from cics.vsam.fct import FctConfig, DatasetConfig
from cics.vsam.seed import seed_records


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_fct_config_from_yaml():
    import yaml

    data = yaml.safe_load(
        "datasets:\n"
        "  ACCTDAT:\n"
        "    file: acctdata.dat\n"
        "    record_length: 300\n"
        "  CARDDAT:\n"
        "    file: carddata.dat\n"
        "    record_length: 150\n"
    )
    config = FctConfig.from_dict(data)
    assert "ACCTDAT" in config.datasets
    assert config.datasets["ACCTDAT"].record_length == 300
    assert config.datasets["CARDDAT"].file == "carddata.dat"


REC_LEN = 10
KEY_LEN = 4


def _rec(key: str, rest: str = "") -> bytes:
    body = rest.ljust(REC_LEN - KEY_LEN)[: REC_LEN - KEY_LEN]
    return (key.ljust(KEY_LEN)[:KEY_LEN] + body).encode()


def _engine_with_records(
    tmp_path: Path, records: list[bytes], rec_len: int = REC_LEN
) -> VsamEngine:
    config = FctConfig(
        datasets={"TESTDS": DatasetConfig(record_length=rec_len, key_length=KEY_LEN)}
    )
    vsam_dir = tmp_path / "vsam"
    seed_records(vsam_dir, config, {"TESTDS": records})
    engine = VsamEngine(config, vsam_dir)
    engine.load_all()
    return engine


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_vsam_engine_loads_dataset(tmp_path: Path) -> None:
    config = FctConfig(datasets={"TESTDS": DatasetConfig(record_length=30)})
    vsam_dir = tmp_path / "vsam"
    seed_records(vsam_dir, config, {"TESTDS": [b"A" * 20 + b"B" * 10]})
    engine = VsamEngine(config, vsam_dir)
    engine.load_all()
    assert engine.dataset_count() == 1


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_vsam_engine_empty_seed_is_ok(tmp_path: Path) -> None:
    config = FctConfig(datasets={"EMPTY": DatasetConfig(record_length=10)})
    engine = VsamEngine(config, tmp_path / "vsam")
    engine.load_all()
    assert engine.dataset_count() == 1


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_existing_record(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "DATA")])
    record, resp = engine.read("TESTDS", b"AA01", KEY_LEN)
    assert resp == RESP_NORMAL
    assert record is not None and record[:KEY_LEN] == b"AA01"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_not_found(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "DATA")])
    _, resp = engine.read("TESTDS", b"ZZ99", KEY_LEN)
    assert resp == RESP_NOTFND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_write_new_record(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [])
    assert engine.write("TESTDS", b"AA01", KEY_LEN, _rec("AA01", "NEW")) == RESP_NORMAL
    _, resp2 = engine.read("TESTDS", b"AA01", KEY_LEN)
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
    record, _ = engine.read("TESTDS", b"AA01", KEY_LEN)
    assert b"UPD" in record


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_rewrite_without_key_extracts_key_from_record(tmp_path: Path):
    """EXEC CICS REWRITE supplies FROM but no RIDFLD — the key must be taken
    from the FROM record itself (its key field), not from the passed key arg
    (which the lowering leaves empty). (CardDemo COACTUPC 9600-WRITE-PROCESSING.)"""
    engine = _engine_with_records(tmp_path, [_rec("AA01", "OLD")])
    assert engine.rewrite("TESTDS", b"", KEY_LEN, _rec("AA01", "UPD")) == RESP_NORMAL
    record, _ = engine.read("TESTDS", b"AA01", KEY_LEN)
    assert b"UPD" in record


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_delete_removes_record(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "DATA")])
    assert engine.delete("TESTDS", b"AA01", KEY_LEN) == RESP_NORMAL
    _, resp2 = engine.read("TESTDS", b"AA01", KEY_LEN)
    assert resp2 == RESP_NOTFND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_keyless_delete_uses_last_read_record(tmp_path: Path):
    """EXEC CICS DELETE without RIDFLD deletes the record most recently READ
    (read-for-update semantics). An empty key falls back to the held key."""
    engine = _engine_with_records(
        tmp_path, [_rec("AA01", "AAAA"), _rec("BB02", "BBBB")]
    )
    # Read BB02 for update, then a keyless DELETE removes exactly that record.
    rec, resp = engine.read("TESTDS", b"BB02", KEY_LEN)
    assert resp == RESP_NORMAL and rec is not None
    assert engine.delete("TESTDS", b"", KEY_LEN) == RESP_NORMAL
    _, gone = engine.read("TESTDS", b"BB02", KEY_LEN)
    assert gone == RESP_NOTFND
    # The other record is untouched.
    _, other = engine.read("TESTDS", b"AA01", KEY_LEN)
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
    rec1, r1 = engine.readnext("TESTDS", cursor)
    rec2, r2 = engine.readnext("TESTDS", cursor)
    _, r3 = engine.readnext("TESTDS", cursor)
    _, r4 = engine.readnext("TESTDS", cursor)
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
    nxt, _ = engine.readnext("TESTDS", cursor)
    assert nxt[:4] == b"BB02"
    # Reversal re-reads the just-read record.
    rev1, r1 = engine.readprev("TESTDS", cursor)
    assert r1 == RESP_NORMAL and rev1[:4] == b"BB02"
    # Continue backward to the prior record.
    rev2, r2 = engine.readprev("TESTDS", cursor)
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
    rec, resp = engine.readprev("TESTDS", cursor)
    assert resp == RESP_NORMAL, f"first READPREV after STARTBR(HIGH) gave resp {resp}"
    assert rec[:4] == b"CC03", f"expected last record CC03, got {rec[:4]!r}"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_startbr_then_readprev_walks_backwards_to_first(tmp_path: Path):
    """A fresh STARTBR(HIGH) then repeated READPREV walks every record in
    descending key order, ending at ENDFILE past the first record."""
    engine = _engine_with_records(tmp_path, [_rec("AA01"), _rec("BB02"), _rec("CC03")])
    cursor = ("task0", "TESTDS", "cur0")
    engine.startbr("TESTDS", b"\xff" * KEY_LEN, KEY_LEN, cursor)
    r1, p1 = engine.readprev("TESTDS", cursor)
    r2, p2 = engine.readprev("TESTDS", cursor)
    r3, p3 = engine.readprev("TESTDS", cursor)
    _, p4 = engine.readprev("TESTDS", cursor)
    assert (p1, r1[:4]) == (RESP_NORMAL, b"CC03")
    assert (p2, r2[:4]) == (RESP_NORMAL, b"BB02")
    assert (p3, r3[:4]) == (RESP_NORMAL, b"AA01")
    assert p4 == RESP_ENDFILE


# ── Key-offset / alternate-key linear scan (red-dragon-7kgb) ─────────


def _engine_offset(
    tmp_path: Path, records: list[bytes], rec_len: int, key_offset: int, key_length: int
) -> VsamEngine:
    config = FctConfig(
        datasets={
            "OFFDS": DatasetConfig(
                record_length=rec_len, key_offset=key_offset, key_length=key_length
            )
        }
    )
    vsam_dir = tmp_path / "vsam"
    seed_records(vsam_dir, config, {"OFFDS": records})
    engine = VsamEngine(config, vsam_dir)
    engine.load_all()
    return engine


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_matches_key_at_nonzero_offset(tmp_path: Path):
    rec = b"C" * 16 + b"000000001" + b"00000000011" + b"\x00" * 4
    engine = _engine_offset(tmp_path, [rec], len(rec), key_offset=25, key_length=11)
    record, resp = engine.read("OFFDS", b"00000000011", 11)
    assert resp == RESP_NORMAL
    assert record is not None
    assert record[25:36] == b"00000000011"
    assert record[16:25] == b"000000001"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_offset_nonmatching_key_notfnd(tmp_path: Path):
    rec = b"C" * 16 + b"000000001" + b"00000000011" + b"\x00" * 4
    engine = _engine_offset(tmp_path, [rec], len(rec), key_offset=25, key_length=11)
    _, resp = engine.read("OFFDS", b"99999999999", 11)
    assert resp == RESP_NOTFND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_read_default_offset_zero_unchanged(tmp_path: Path):
    engine = _engine_with_records(tmp_path, [_rec("AA01", "DATA")])
    record, resp = engine.read("TESTDS", b"AA01", KEY_LEN)
    assert resp == RESP_NORMAL
    assert record is not None and record[:KEY_LEN] == b"AA01"


# ── Backing-file is the store (write lands on disk) ──────────────────


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_write_lands_on_backing_file_and_survives_new_engine(tmp_path: Path) -> None:
    """A WRITE goes straight to the backing .dat (the file IS the store); a fresh
    engine over the same vsam_dir reads it back."""
    config = FctConfig(datasets={"DS": DatasetConfig(record_length=4, key_length=4)})
    vsam_dir = tmp_path / "vsam"
    seed_records(vsam_dir, config, {"DS": [b"AAAA"]})
    eng = VsamEngine(config, vsam_dir)
    eng.load_all()
    assert eng.write("DS", b"ZZZZ", 4, b"ZZZZ") == RESP_NORMAL

    from cics.vsam.format import read_flat_file

    assert read_flat_file(vsam_dir / "DS.dat", 4) == [b"AAAA", b"ZZZZ"]

    eng2 = VsamEngine(config, vsam_dir)
    eng2.load_all()
    rec, resp = eng2.read("DS", b"ZZZZ", 4)
    assert resp == RESP_NORMAL and rec == b"ZZZZ"
