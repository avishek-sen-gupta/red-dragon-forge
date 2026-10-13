"""
tests/unit/test_preprocess.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for squall.preprocess.apply_sql_prepass.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from squall.parser.parse import parse_exec_sql
from squall.parser.sql_model import IncludeName, NoInclude
from squall.preprocess import apply_sql_prepass

# ── include field on ParsedSql ────────────────────────────────────────────────


def test_include_populated_for_include() -> None:
    p = parse_exec_sql("EXEC SQL INCLUDE SQLCA END-EXEC")
    assert p.include == IncludeName("SQLCA")


def test_include_noinclude_for_select() -> None:
    p = parse_exec_sql("EXEC SQL SELECT a INTO :x FROM t END-EXEC")
    assert p.include == NoInclude()


# ── apply_sql_prepass ─────────────────────────────────────────────────────────


def test_include_rewritten_with_cobol_indentation() -> None:
    """EXEC SQL INCLUDE with leading COBOL indent → COPY at same indent."""
    source = "       EXEC SQL INCLUDE SQLCA END-EXEC."
    result = apply_sql_prepass(source)
    assert result == "       COPY SQLCA."


def test_select_block_unchanged() -> None:
    """An EXEC SQL SELECT … END-EXEC block is returned byte-for-byte."""
    source = (
        "       EXEC SQL SELECT acct_bal INTO :WS-BAL\n"
        "           FROM account WHERE acct_id = :WS-ID\n"
        "       END-EXEC."
    )
    assert apply_sql_prepass(source) == source


def test_plain_cobol_line_unchanged() -> None:
    """Ordinary COBOL that contains no EXEC SQL is returned unchanged."""
    source = "       MOVE WS-FOO TO WS-BAR."
    assert apply_sql_prepass(source) == source


def test_two_includes_both_rewritten() -> None:
    """Multiple INCLUDE blocks in one source are each rewritten."""
    source = (
        "       EXEC SQL INCLUDE SQLCA END-EXEC.\n"
        "       MOVE 1 TO WS-X.\n"
        "       EXEC SQL INCLUDE SQLDA END-EXEC."
    )
    expected = "       COPY SQLCA.\n" "       MOVE 1 TO WS-X.\n" "       COPY SQLDA."
    assert apply_sql_prepass(source) == expected


def test_lowercase_include_rewritten() -> None:
    """Delimiters and INCLUDE keyword are matched case-insensitively."""
    source = "       exec sql include sqlca end-exec."
    result = apply_sql_prepass(source)
    assert result == "       COPY SQLCA."


def test_mixed_cobol_and_sql_blocks() -> None:
    """Source with INCLUDE, plain COBOL, and a SELECT all handled correctly."""
    source = (
        "       EXEC SQL INCLUDE SQLCA END-EXEC.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       EXEC SQL SELECT 1 INTO :X FROM SYSIBM.SYSDUMMY1 END-EXEC."
    )
    result = apply_sql_prepass(source)
    assert "       COPY SQLCA." in result
    assert "       WORKING-STORAGE SECTION." in result
    assert "EXEC SQL SELECT" in result  # SELECT block unchanged


# ── fixed-format sequence numbers (columns 1-6) ─────────────────────────────────


def test_exec_sql_include_is_rewritten_with_fixed_format_sequence_numbers() -> None:
    """Columns 1-6 are the ignored sequence area in fixed-format COBOL.
    CardDemo's Db2 programs carry them; EXEC SQL must still be detected."""
    source = "028600      EXEC SQL INCLUDE DCLTRTYP END-EXEC\n"

    result = apply_sql_prepass(source)

    assert "COPY DCLTRTYP." in result
    assert "EXEC SQL" not in result


def test_sequence_numbers_are_preserved_so_copy_stays_in_area_b() -> None:
    source = "028600      EXEC SQL INCLUDE DCLTRTYP END-EXEC\n"

    result = apply_sql_prepass(source)

    assert result.startswith("028600      COPY")


def test_unnumbered_exec_sql_still_works() -> None:
    """The existing form must be untouched by the fix."""
    source = "           EXEC SQL INCLUDE SQLCA END-EXEC\n"

    result = apply_sql_prepass(source)

    assert "COPY SQLCA." in result


def test_include_rewrite_preserves_the_identification_area() -> None:
    """The defect that corrupted CARDDEMO-COMMAREA: the rewrite was 20 chars
    shorter, so 02860000 slid from column 73 into Area B."""
    source = "028600      EXEC SQL INCLUDE DCLTRTYP END-EXEC                          02860000\n"

    result = apply_sql_prepass(source)

    line = result.splitlines()[0]
    assert line[72:80] == "02860000"
    assert "COPY DCLTRTYP." in line[7:72]
    assert "02860000" not in line[7:72]


# ── Real-corpus check ────────────────────────────────────────────────────────
# Resolution order for CARDDEMO_HOME, matching test_fixed_format.py's real-corpus
# gate: (1) CARDDEMO_HOME env var, (2) vendor/carddemo/app submodule, auto-detected
# from the monorepo root. A wrong override or a missing submodule fails the test
# outright — it never degrades to a skip.

_MONOREPO_ROOT = Path(__file__).resolve().parents[3]
_SUBMODULE_CARDDEMO_APP = _MONOREPO_ROOT / "vendor" / "carddemo" / "app"
_CARDDEMO_HOME = Path(os.environ.get("CARDDEMO_HOME") or _SUBMODULE_CARDDEMO_APP)


def test_real_cotrtupc_prepass_preserves_the_identification_area_on_every_line() -> (
    None
):
    """The revert-sensitive real-file check: every line's identification area
    (columns 73-80) matches the source's, whatever the prepass did to the
    code area, and the line count is unchanged.

    A ``\\s*\\d{8}\\s*`` bare-token scan over the *rewritten* code area does
    NOT pin this: the pre-migration corruption produces e.g.
    ``028600      COPY DCLTRTYP.                          02860000`` — the
    stray ``02860000`` shares its code area with ``COPY``, so it is never a
    *bare* sequence-shaped token, and re-running the pre-migration
    ``apply_sql_prepass`` over this same file left that assertion matching
    zero lines (verified: 0 failures, false green). Comparing column 73-80
    directly against the source catches it: reverting the fix corrupts 2
    lines in this file — 286 and 288 (each an ``EXEC SQL INCLUDE ... END-EXEC``
    on one line, 20+ characters shorter as ``COPY``).

    ``re.search(r"\\d{8}", ...)`` was also considered and rejected — line 237
    of this file has the legitimate ``VALUE '0123456789'``, which it would
    false-positive on.
    """
    db2 = _CARDDEMO_HOME / "app-transaction-type-db2"
    source_path = db2 / "cbl" / "COTRTUPC.cbl"
    if not source_path.is_file():
        pytest.fail(
            "CardDemo corpus not found for the real-file prepass check "
            f"(resolved CARDDEMO_HOME={_CARDDEMO_HOME}); missing: {source_path}. "
            "Run `git submodule update --init vendor/carddemo`, or set CARDDEMO_HOME.",
            pytrace=False,
        )
    source = source_path.read_text(encoding="latin-1")

    result = apply_sql_prepass(source)

    source_lines = source.splitlines()
    rewritten_lines = result.splitlines()
    assert len(rewritten_lines) == len(source_lines)
    for number, (before, after) in enumerate(
        zip(source_lines, rewritten_lines), start=1
    ):
        assert after[72:80] == before[72:80], f"line {number}"


# ── line endings ─────────────────────────────────────────────────────────────


def test_crlf_line_endings_are_preserved() -> None:
    """Mainframe-sourced files are commonly CRLF. render()'s deliberate rstrip
    of a line with no identification area must not eat every '\\r' in the
    file as a side effect of rewriting one INCLUDE."""
    source = "       EXEC SQL INCLUDE SQLCA END-EXEC.\r\n       MOVE 1 TO WS-X.\r\n"

    result = apply_sql_prepass(source)

    assert result == "       COPY SQLCA.\r\n       MOVE 1 TO WS-X.\r\n"


def test_line_endings_are_preserved_whether_or_not_source_has_an_include() -> None:
    """The same CRLF input must not produce different line endings depending
    on whether it happens to contain EXEC SQL — the early-return-on-no-includes
    path and the rewrite path must agree."""
    plain = "       MOVE 1 TO WS-X.\r\n       MOVE 2 TO WS-Y.\r\n"
    with_include = (
        "       EXEC SQL INCLUDE SQLCA END-EXEC.\r\n       MOVE 2 TO WS-Y.\r\n"
    )

    assert apply_sql_prepass(plain).count("\r\n") == 2
    assert apply_sql_prepass(with_include).count("\r\n") == 2


# ── trailing code after END-EXEC on the same physical line ───────────────────


def test_trailing_cobol_after_end_exec_on_the_same_line_is_preserved() -> None:
    """A second statement's worth of plain COBOL immediately following
    END-EXEC on the same physical line must not vanish. replace_span blanks
    whole code areas; a rewrite must fold this trailing text back in rather
    than losing it, as the character-range splice it replaced never did."""
    source = "       EXEC SQL INCLUDE AAA END-EXEC. MOVE 1 TO WS-X.\n"

    result = apply_sql_prepass(source)

    assert result == "       COPY AAA. MOVE 1 TO WS-X.\n"


def test_a_second_exec_sql_on_the_same_line_is_preserved_though_not_rewritten() -> None:
    """A second EXEC SQL sharing the first's physical line is not itself
    recognised as its own span (the scan only matches at a code area's
    start), but it must survive the first span's rewrite verbatim rather
    than being discarded along with it."""
    source = "       EXEC SQL INCLUDE AAA END-EXEC. EXEC SQL INCLUDE BBB END-EXEC.\n"

    result = apply_sql_prepass(source)

    assert result == "       COPY AAA. EXEC SQL INCLUDE BBB END-EXEC.\n"
