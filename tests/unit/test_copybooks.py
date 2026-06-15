"""
tests/unit/test_copybooks.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The bundled copybooks that `EXEC SQL INCLUDE` expands to must be present and
resolvable as package resources, with the field shapes the typed codec exercises.
"""

from __future__ import annotations

from importlib.resources import files


def _read(name: str) -> str:
    return files("squall.copybooks").joinpath(name).read_text(encoding="utf-8")


def test_sqlca_present_with_binary_sqlcode() -> None:
    text = _read("SQLCA.cpy")
    assert "01  SQLCA." in text
    # SQLCODE is a binary COMP field — the real SQLCA contract (not a hand zoned field).
    assert "SQLCODE    PIC S9(9) COMP." in text


def test_acctrec_dclgen_record_present() -> None:
    text = _read("ACCTREC.cpy")
    assert "01  ACCT-REC." in text
    assert "ACCT-ID    PIC S9(9) COMP." in text  # binary COMP
    assert "ACCT-BAL   PIC S9(7)V9(2) COMP-3." in text  # scaled packed decimal
    assert "ACCT-NAME  PIC X(20)." in text  # CHAR (VARCHAR deferred)


def test_copybook_dir_is_a_real_filesystem_path() -> None:
    # The prepass wires this dir into the parser's copybook_dirs, so it must be a
    # concrete directory on disk (not a zip resource).
    d = files("squall.copybooks")
    assert (d / "SQLCA.cpy").is_file()
    assert (d / "ACCTREC.cpy").is_file()
