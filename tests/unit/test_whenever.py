"""
tests/unit/test_whenever.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
EXEC SQL WHENEVER <condition> <action> — a precompiler directive that squall
surfaces on ParsedSql and the strategy applies as lexically-scoped automatic
SQLCODE branching. Slice 1: SQLERROR / NOT FOUND with CONTINUE / GO TO.
"""

from __future__ import annotations

from squall.parser.parse import parse_exec_sql


def test_parse_whenever_sqlerror_goto():
    p = parse_exec_sql("EXEC SQL WHENEVER SQLERROR GOTO ERR-EXIT END-EXEC")
    assert p.kind == "whenever"
    assert p.whenever_condition == "SQLERROR"
    assert p.whenever_action == "GOTO"
    assert p.whenever_target == "ERR-EXIT"


def test_parse_whenever_go_to_two_words():
    p = parse_exec_sql("EXEC SQL WHENEVER SQLERROR GO TO ERR-EXIT END-EXEC")
    assert p.whenever_action == "GOTO"
    assert p.whenever_target == "ERR-EXIT"


def test_parse_whenever_not_found_continue():
    p = parse_exec_sql("EXEC SQL WHENEVER NOT FOUND CONTINUE END-EXEC")
    assert p.kind == "whenever"
    assert p.whenever_condition == "NOT FOUND"
    assert p.whenever_action == "CONTINUE"
    assert p.whenever_target is None


def test_parse_non_whenever_has_no_whenever_fields():
    p = parse_exec_sql("EXEC SQL SELECT a INTO :x FROM t END-EXEC")
    assert p.whenever_condition is None
    assert p.whenever_action is None
    assert p.whenever_target is None
