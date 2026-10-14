"""Raw fixed-length-record flat-file codec for VSAM dataset images."""

from __future__ import annotations

from pathlib import Path

import pytest

from cics.vsam.format import read_flat_file
from tests.covers import covers, NotLanguageFeature


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_flat_file_reads_as_its_fixed_length_records(tmp_path: Path) -> None:
    p = tmp_path / "ds.dat"
    p.write_bytes(b"AAAABBBBCCCC")
    assert read_flat_file(p, 4) == [b"AAAA", b"BBBB", b"CCCC"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_missing_file_reads_empty(tmp_path: Path) -> None:
    assert read_flat_file(tmp_path / "nope.dat", 4) == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_size_not_multiple_of_record_length_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.dat"
    p.write_bytes(b"AAAAB")  # 5 bytes, record_length 4
    with pytest.raises(ValueError):
        read_flat_file(p, 4)
