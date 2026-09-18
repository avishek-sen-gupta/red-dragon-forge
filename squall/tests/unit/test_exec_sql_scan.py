"""
tests/unit/test_exec_sql_scan.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for squall.exec_sql_scan.find_exec_sql_spans — the cursor-advancing
EXEC SQL / END-EXEC block scanner used by squall.preprocess.
"""

from __future__ import annotations

from squall.exec_sql_scan import find_exec_sql_spans
from squall.parser.parse import parse_exec_sql
from squall.parser.sql_model import HostVar, Kind

# ── multi-line, fixed-format sequence numbers ───────────────────────────────


def test_multiline_sequence_numbered_select_into_strips_digits_from_every_line() -> (
    None
):
    """The opening-line regex only strips columns 1-6 on the first line of a
    block; a multi-line statement's continuation lines carry their own
    sequence numbers, which must not leak into the text handed to the SQL
    parser."""
    source = (
        "028600  EXEC SQL SELECT TR_TYPE\n"
        "028700          INTO :DCL-TR-TYPE\n"
        "028800          FROM TRAN_TYPE\n"
        "028900  END-EXEC.\n"
    )

    (span,) = find_exec_sql_spans(source)

    assert not any(ch.isdigit() for ch in span.parse_text)


def test_multiline_sequence_numbered_select_into_is_recognised_with_into() -> None:
    """The parser must see a real SELECT INTO — not Kind.GENERIC with the
    INTO clause swallowed as unrecognised text — once digits are stripped."""
    source = (
        "028600  EXEC SQL SELECT TR_TYPE\n"
        "028700          INTO :DCL-TR-TYPE\n"
        "028800          FROM TRAN_TYPE\n"
        "028900  END-EXEC.\n"
    )

    (span,) = find_exec_sql_spans(source)
    parsed = parse_exec_sql(span.parse_text)

    assert parsed.kind is Kind.SELECT_INTO
    assert parsed.out_vars == (HostVar(name="DCL-TR-TYPE", indicator=None),)


def test_non_include_sequence_numbered_statement_is_scanned() -> None:
    """Sequence numbers must not block detection of non-INCLUDE statements —
    apply_sql_prepass's own INCLUDE-only tests can't exercise this branch."""
    source = "012300  EXEC SQL COMMIT END-EXEC.\n"

    (span,) = find_exec_sql_spans(source)
    parsed = parse_exec_sql(span.parse_text)

    assert parsed.kind is Kind.COMMIT


def test_sequence_numbered_end_exec_with_trailing_dot() -> None:
    """The trailing statement-terminator dot must still be consumed into the
    replace span when END-EXEC's line also carries a sequence number."""
    source = "045600  EXEC SQL INCLUDE SQLCA END-EXEC.\n"

    (span,) = find_exec_sql_spans(source)

    assert source[span.replace_start : span.replace_end] == (
        "045600  EXEC SQL INCLUDE SQLCA END-EXEC."
    )


def test_mixed_numbered_and_unnumbered_source() -> None:
    """A source mixing sequence-numbered and unnumbered EXEC SQL blocks (as
    real corpora do) must locate both, each keeping its own indent."""
    source = (
        "028600      EXEC SQL INCLUDE DCLTRTYP END-EXEC\n"
        "       EXEC SQL INCLUDE SQLCA END-EXEC\n"
    )

    first, second = find_exec_sql_spans(source)

    assert first.indent == "028600      "
    assert second.indent == "       "


# ── no recursion ceiling ─────────────────────────────────────────────────────


def test_many_statements_do_not_raise_recursion_error() -> None:
    """Regression: a recursive-unfold rewrite of this scan raised
    RecursionError at roughly 1000 EXEC SQL statements in one source (900
    passed, 1200 crashed). The iterative scan must handle well past that."""
    source = "       EXEC SQL INCLUDE SQLCA END-EXEC.\n" * 1500

    spans = find_exec_sql_spans(source)

    assert len(spans) == 1500


# ── malformed source ─────────────────────────────────────────────────────────


def test_exec_sql_without_end_exec_is_skipped() -> None:
    """A block missing its END-EXEC delimiter is malformed and skipped —
    scanning continues past it rather than raising or looping."""
    source = "       EXEC SQL INCLUDE SQLCA\n       MOVE 1 TO WS-X.\n"

    spans = find_exec_sql_spans(source)

    assert spans == ()


def test_well_formed_block_found_before_a_later_malformed_one() -> None:
    """A well-formed block is still found when a malformed one (no END-EXEC
    anywhere in the rest of the source) follows it — the skip on the second
    occurrence must not disturb the first span already collected."""
    source = "       EXEC SQL INCLUDE SQLCA END-EXEC.\n       EXEC SQL INCLUDE BROKEN\n"

    (span,) = find_exec_sql_spans(source)
    parsed = parse_exec_sql(span.parse_text)

    assert parsed.include.name == "SQLCA"
