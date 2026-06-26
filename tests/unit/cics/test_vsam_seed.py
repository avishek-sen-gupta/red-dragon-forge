"""Tests for seed_vsam (backing-file writer) + base-KSDS key sort."""

from __future__ import annotations

from pathlib import Path

import yaml

from cics.vsam.fct import DatasetConfig, FctConfig
from cics.vsam.format import read_flat_file
from cics.vsam.seed import seed_records, seed_vsam
from tests.covers import NotLanguageFeature, covers


def _write_fct(path: Path, datasets: dict) -> None:
    path.write_text(yaml.dump({"datasets": datasets}))


def _write_flat(path: Path, records: list[bytes]) -> None:
    path.write_bytes(b"".join(records))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_seed_vsam_writes_dat_files(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    vsam_dir = tmp_path / "vsam"
    _write_flat(data_dir / "acct.dat", [b"AAAA", b"BBBB"])
    _write_fct(
        tmp_path / "fct.yaml",
        {"ACCTFILE": {"file": "acct.dat", "record_length": 4}},
    )

    seed_vsam(tmp_path / "fct.yaml", data_dir, vsam_dir)

    dat = vsam_dir / "ACCTFILE.dat"
    assert dat.exists()
    assert read_flat_file(dat, 4) == [b"AAAA", b"BBBB"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_seed_vsam_creates_vsam_dir_if_missing(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    vsam_dir = tmp_path / "vsam" / "nested"
    _write_flat(data_dir / "acct.dat", [b"AAAA"])
    _write_fct(
        tmp_path / "fct.yaml",
        {"ACCTFILE": {"file": "acct.dat", "record_length": 4}},
    )

    seed_vsam(tmp_path / "fct.yaml", data_dir, vsam_dir)

    assert (vsam_dir / "ACCTFILE.dat").exists()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_seed_vsam_source_files_untouched(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    vsam_dir = tmp_path / "vsam"
    original = b"AAAA"
    (data_dir / "acct.dat").write_bytes(original)
    _write_fct(
        tmp_path / "fct.yaml",
        {"ACCTFILE": {"file": "acct.dat", "record_length": 4}},
    )

    seed_vsam(tmp_path / "fct.yaml", data_dir, vsam_dir)

    assert (data_dir / "acct.dat").read_bytes() == original


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_seed_records_base_ksds_is_key_sorted(tmp_path: Path) -> None:
    """A base KSDS (key_offset=0) backing file must be physically key-sorted so
    the file-resident IndexedDriver binary search applies — even when the source
    records arrive out of key order."""
    vsam_dir = tmp_path / "vsam"
    fct = FctConfig(
        datasets={"DS": DatasetConfig(record_length=8, key_offset=0, key_length=3)}
    )
    unsorted = [b"CCC00003", b"AAA00001", b"BBB00002"]

    seed_records(vsam_dir, fct, {"DS": unsorted})

    assert read_flat_file(vsam_dir / "DS.dat", 8) == [
        b"AAA00001",
        b"BBB00002",
        b"CCC00003",
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_seed_records_alternate_key_keeps_source_order(tmp_path: Path) -> None:
    """An alternate-key dataset (key_offset>0) is read by linear scan, so its
    backing file is written in source order — NOT sorted by the alt key."""
    vsam_dir = tmp_path / "vsam"
    fct = FctConfig(
        datasets={"AIX": DatasetConfig(record_length=8, key_offset=4, key_length=4)}
    )
    # Sorted by primary (offset 0), unsorted by the alt key at offset 4.
    source = [b"0001ZZZZ", b"0002AAAA", b"0003MMMM"]

    seed_records(vsam_dir, fct, {"AIX": source})

    assert read_flat_file(vsam_dir / "AIX.dat", 8) == source


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_seed_vsam_sorts_base_ksds_from_ebcdic_source(tmp_path: Path) -> None:
    """End to end: seed_vsam reads an out-of-order source and writes a key-sorted
    base-KSDS .dat."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    vsam_dir = tmp_path / "vsam"
    _write_flat(data_dir / "ds.dat", [b"CCC", b"AAA", b"BBB"])
    _write_fct(
        tmp_path / "fct.yaml",
        {"DS": {"file": "ds.dat", "record_length": 3, "key_length": 3}},
    )

    seed_vsam(tmp_path / "fct.yaml", data_dir, vsam_dir)

    assert read_flat_file(vsam_dir / "DS.dat", 3) == [b"AAA", b"BBB", b"CCC"]
