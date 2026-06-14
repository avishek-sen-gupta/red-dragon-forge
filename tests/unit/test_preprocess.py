"""
tests/unit/test_preprocess.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for squall.preprocess.apply_sql_prepass.
"""

from __future__ import annotations

import pytest

from squall.parser.parse import parse_exec_sql
from squall.preprocess import apply_sql_prepass


# ── include_name field on ParsedSql ──────────────────────────────────────────


def test_include_name_populated_for_include() -> None:
    p = parse_exec_sql("EXEC SQL INCLUDE SQLCA END-EXEC")
    assert p.include_name == "SQLCA"


def test_include_name_none_for_select() -> None:
    p = parse_exec_sql(
        "EXEC SQL SELECT a INTO :x FROM t END-EXEC"
    )
    assert p.include_name is None


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
    expected = (
        "       COPY SQLCA.\n"
        "       MOVE 1 TO WS-X.\n"
        "       COPY SQLDA."
    )
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
