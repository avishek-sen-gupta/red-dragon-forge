"""
tests/unit/test_parse.py
~~~~~~~~~~~~~~~~~~~~~~~~
Tests for squall.parser.parse: parse_exec_sql, HostVar, ParsedSql.
"""

from __future__ import annotations

import pytest

from squall.parser.parse import HostVar, ParsedSql, parse_exec_sql


# ── Required tests from spec ──────────────────────────────────────────────────


def test_select_into() -> None:
    p = parse_exec_sql(
        "EXEC SQL SELECT acct_bal INTO :WS-BAL FROM account WHERE acct_id = :WS-ID END-EXEC"
    )
    assert p.kind == "select_into"
    assert p.out_vars == (HostVar("WS-BAL", None),)
    assert p.in_vars == (HostVar("WS-ID", None),)
    assert p.query == "SELECT acct_bal FROM account WHERE acct_id = ?"


def test_update_input_order() -> None:
    p = parse_exec_sql(
        "EXEC SQL UPDATE CONTROL SET V = :HV-V WHERE N = :HV-N END-EXEC"
    )
    assert p.in_vars == (HostVar("HV-V", None), HostVar("HV-N", None))
    assert p.out_vars == ()
    assert p.query == "UPDATE CONTROL SET V = ? WHERE N = ?"


def test_fetch_outputs_no_query() -> None:
    p = parse_exec_sql("EXEC SQL FETCH FROM ACC-CURSOR INTO :A, :B END-EXEC")
    assert p.kind == "fetch" and p.cursor == "ACC-CURSOR"
    assert p.out_vars == (HostVar("A", None), HostVar("B", None))
    assert p.query == ""


def test_indicator_var() -> None:
    p = parse_exec_sql(
        "EXEC SQL SELECT bal INTO :WS-BAL:WS-IND FROM t WHERE id = :ID END-EXEC"
    )
    assert p.out_vars == (HostVar("WS-BAL", "WS-IND"),)
    assert p.in_vars == (HostVar("ID", None),)


def test_string_colon_not_a_host_var() -> None:
    p = parse_exec_sql(
        "EXEC SQL SELECT n INTO :OUT FROM t WHERE x = 'a :colon b' AND y = :IN END-EXEC"
    )
    assert p.in_vars == (HostVar("IN", None),)
    assert "?" in p.query and ":colon" in p.query


# ── Additional tests ──────────────────────────────────────────────────────────


def test_insert_values() -> None:
    """INSERT with VALUES host vars -> all inputs (in_vars), out_vars == ()."""
    p = parse_exec_sql(
        "EXEC SQL INSERT INTO account (acct_id, acct_bal) VALUES (:HV-ID, :HV-BAL) END-EXEC"
    )
    assert p.kind == "insert"
    assert p.out_vars == ()
    assert p.in_vars == (HostVar("HV-ID", None), HostVar("HV-BAL", None))
    assert p.query == "INSERT INTO account (acct_id, acct_bal) VALUES (?, ?)"
    assert p.cursor is None


def test_declare_cursor() -> None:
    """declare_cursor -> cursor name + the SELECT's WHERE host vars as in_vars."""
    p = parse_exec_sql(
        "EXEC SQL DECLARE ACC-CURSOR CURSOR FOR SELECT * FROM account WHERE id = :WS-ID END-EXEC"
    )
    assert p.kind == "declare_cursor"
    assert p.cursor == "ACC-CURSOR"
    assert p.in_vars == (HostVar("WS-ID", None),)
    assert p.out_vars == ()


# ── Additional edge case tests ────────────────────────────────────────────────


def test_cursor_is_none_for_non_cursor_stmt() -> None:
    """Non-cursor statements have cursor == None."""
    p = parse_exec_sql("EXEC SQL SELECT a INTO :X FROM t END-EXEC")
    assert p.cursor is None


def test_open_cursor_no_query() -> None:
    """OPEN cursor -> query == ''."""
    p = parse_exec_sql("EXEC SQL OPEN MyCursor END-EXEC")
    assert p.kind == "open_"
    assert p.cursor == "MyCursor"
    assert p.query == ""


def test_close_cursor_no_query() -> None:
    """CLOSE cursor -> query == ''."""
    p = parse_exec_sql("EXEC SQL CLOSE MyCursor END-EXEC")
    assert p.kind == "close"
    assert p.cursor == "MyCursor"
    assert p.query == ""


def test_delete_with_host_var() -> None:
    """DELETE with host var in WHERE -> in_vars captured."""
    p = parse_exec_sql("EXEC SQL DELETE FROM t WHERE id = :HV-ID END-EXEC")
    assert p.kind == "delete"
    assert p.in_vars == (HostVar("HV-ID", None),)
    assert p.out_vars == ()
    assert p.query == "DELETE FROM t WHERE id = ?"


def test_commit_no_host_vars() -> None:
    """COMMIT has no host vars and no query."""
    p = parse_exec_sql("EXEC SQL COMMIT END-EXEC")
    assert p.kind == "commit"
    assert p.in_vars == ()
    assert p.out_vars == ()
    assert p.cursor is None


def test_envelope_strip_case_insensitive() -> None:
    """EXEC SQL / END-EXEC stripping is case-insensitive."""
    p = parse_exec_sql("exec sql SELECT a INTO :X FROM t end-exec")
    assert p.kind == "select_into"
    assert p.out_vars == (HostVar("X", None),)


def test_returned_types_are_frozen() -> None:
    """ParsedSql and HostVar must be immutable (frozen dataclasses)."""
    p = parse_exec_sql("EXEC SQL SELECT a INTO :X FROM t END-EXEC")
    with pytest.raises((AttributeError, TypeError)):
        p.kind = "something_else"  # type: ignore[misc]
    hv = p.out_vars[0]
    with pytest.raises((AttributeError, TypeError)):
        hv.name = "changed"  # type: ignore[misc]


def test_values_into() -> None:
    """VALUES … INTO -> out_vars captured, no input host vars in value list."""
    p = parse_exec_sql("EXEC SQL VALUES (:HV-IN) INTO :HV-OUT END-EXEC")
    assert p.kind == "values_into"
    assert p.out_vars == (HostVar("HV-OUT", None),)
    assert p.in_vars == (HostVar("HV-IN", None),)
    assert p.query == "VALUES (?)"
