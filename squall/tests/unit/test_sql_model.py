"""
tests/unit/test_sql_model.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The pure-data SQL model types: frozen-dataclass value equality, enum identity,
and that enums are NOT implicitly comparable to strings (proper Enum, not StrEnum).
"""

from __future__ import annotations

from squall.parser.sql_model import (
    ConnectReset,
    ConnectTo,
    Continue,
    GoTo,
    HostVar,
    HostVarDb,
    IncludeName,
    Kind,
    LiteralDb,
    NamedCursor,
    NoConnect,
    NoCursor,
    NoInclude,
    NoOpAction,
    WheneverCondition,
)


def test_kind_constructs_from_grammar_string_but_is_not_a_string():
    assert Kind("select_into") is Kind.SELECT_INTO
    assert Kind.SELECT_INTO != "select_into"  # proper Enum, no implicit str equality


def test_whenever_condition_constructs_and_is_not_a_string():
    assert WheneverCondition("NOT FOUND") is WheneverCondition.NOT_FOUND
    assert WheneverCondition.SQLERROR != "SQLERROR"


def test_dataclass_sums_compare_by_value():
    assert NamedCursor("C1") == NamedCursor("C1")
    assert NamedCursor("C1") != NoCursor()
    assert GoTo("ERR") == GoTo("ERR")
    assert GoTo("ERR") != Continue()
    assert ConnectTo(LiteralDb("SAMPLE")) == ConnectTo(LiteralDb("SAMPLE"))
    assert ConnectTo(HostVarDb(HostVar("DB", None))) != ConnectReset()


def test_null_objects_are_distinct_singletons_by_type():
    assert NoCursor() == NoCursor()
    assert NoInclude() == NoInclude()
    assert NoConnect() == NoConnect()
    assert NoOpAction() == NoOpAction()
