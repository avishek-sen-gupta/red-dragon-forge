"""
tests/unit/test_whenever.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
EXEC SQL WHENEVER <condition> <action> — a precompiler directive that squall
surfaces on ParsedSql and the strategy applies as lexically-scoped automatic
SQLCODE branching. Slice 1: SQLERROR / NOT FOUND with CONTINUE / GO TO.
"""

from __future__ import annotations

import pytest

from squall.parser.parse import parse_exec_sql
from squall.parser.sql_model import (
    Continue,
    GoTo,
    Kind,
    NoOpAction,
    WheneverCondition,
)


def test_parse_whenever_sqlerror_goto():
    p = parse_exec_sql("EXEC SQL WHENEVER SQLERROR GOTO ERR-EXIT END-EXEC")
    assert p.kind is Kind.WHENEVER
    assert p.whenever_condition is WheneverCondition.SQLERROR
    assert p.whenever_action == GoTo("ERR-EXIT")


def test_parse_whenever_go_to_two_words():
    p = parse_exec_sql("EXEC SQL WHENEVER SQLERROR GO TO ERR-EXIT END-EXEC")
    assert p.whenever_action == GoTo("ERR-EXIT")


@pytest.mark.parametrize(
    ("action", "label"),
    [
        ("GOTO ERR-EXIT", "ERR-EXIT"),
        ("GO TO ERR-EXIT", "ERR-EXIT"),
        ("GOTO :ERR-EXIT", "ERR-EXIT"),
        ("GO TO :ERR-EXIT", "ERR-EXIT"),
        ("GO TO 9000-ERR-EXIT", "9000-ERR-EXIT"),
        ("GOTO :9000-ERR-EXIT", "9000-ERR-EXIT"),
        ("GO TO 9000", "9000"),
    ],
)
def test_the_target_of_a_go_to_is_its_whole_label_with_or_without_a_colon(
    action: str, label: str
) -> None:
    """Db2 lets the host label carry a colon, and a COBOL paragraph name may start
    with digits. Either one the grammar did not take fell through to the catch-all,
    whose last token -- TO, or the part after the digits -- came back as the target."""
    p = parse_exec_sql(f"EXEC SQL WHENEVER SQLERROR {action} END-EXEC")

    assert (p.kind, p.whenever_action) == (Kind.WHENEVER, GoTo(label))


def test_parse_whenever_not_found_continue():
    p = parse_exec_sql("EXEC SQL WHENEVER NOT FOUND CONTINUE END-EXEC")
    assert p.kind is Kind.WHENEVER
    assert p.whenever_condition is WheneverCondition.NOT_FOUND
    assert p.whenever_action == Continue()


def test_parse_non_whenever_has_no_whenever_fields():
    p = parse_exec_sql("EXEC SQL SELECT a INTO :x FROM t END-EXEC")
    assert p.whenever_condition is WheneverCondition.NONE
    assert p.whenever_action == NoOpAction()


# ── Strategy: WHENEVER lowers to a synthetic conditional branch ────────────────

import importlib.util
import os
from pathlib import Path

from interpreter.instructions import BranchIf

_HELPERS = Path(__file__).parent.parent / "integration" / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
compile_cobol = _helpers.compile_cobol


_PROGRAM_GOTO = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. WHENT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01 WS-ID PIC 9(4) VALUE 1.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL WHENEVER SQLERROR GO TO ERR-PARA END-EXEC
           EXEC SQL SELECT 1 INTO :WS-ID FROM SYSIBM.SYSDUMMY1 END-EXEC
           STOP RUN.
       ERR-PARA.
           STOP RUN.
"""


def test_whenever_goto_emits_conditional_branch(bridge_jar=None):
    """A SELECT under an active WHENEVER SQLERROR GO TO lowers a BranchIf
    (the synthetic IF SQLCODE < 0 GO TO ERR-PARA) into the IR."""
    jar = os.environ["PROLEAP_BRIDGE_JAR"]
    linked = compile_cobol(_PROGRAM_GOTO, jar, copybook_dirs=[])
    assert any(
        isinstance(i, BranchIf) for i in linked.merged_ir
    ), "expected a conditional branch from the synthetic WHENEVER IF/GO TO"


@pytest.mark.parametrize(
    "action",
    ["DO HANDLER()", "PERFORM ERR-PARA", "STOP"],
    ids=["do", "perform", "stop"],
)
def test_an_action_db2_does_not_define_is_not_a_jump(action: str) -> None:
    """PERFORM/STOP/DO are Pro*COBOL, not Db2. Reading them as GO TO invented a
    target -- `DO HANDLER()` became GoTo(')') and `STOP` a jump to a paragraph
    named STOP -- which a CFG then drew an edge to."""
    plan = parse_exec_sql(f"EXEC SQL WHENEVER SQLERROR {action} END-EXEC")

    assert plan.whenever_condition == WheneverCondition.SQLERROR
    assert plan.whenever_action == NoOpAction()


def test_not_found_with_an_unsupported_action_is_unmodelled_rather_than_fatal() -> None:
    """This used to raise out of the enum lookup, which reached cobble's corpus
    parse as a member it could no longer parse at all.

    The condition still comes back NONE rather than NOT_FOUND: the opaque-run
    action alternative takes FOUND, leaving the condition tokens as bare NOT.
    Binding NOT FOUND tighter is grammar surgery that buys nothing here, because
    PERFORM is an action Db2 does not define and no branch is emitted for it
    either way. What matters is that it neither raises nor invents a jump."""
    plan = parse_exec_sql("EXEC SQL WHENEVER NOT FOUND PERFORM H END-EXEC")

    assert plan.whenever_condition == WheneverCondition.NONE
    assert plan.whenever_action == NoOpAction()


def test_a_condition_db2_does_not_define_does_not_raise() -> None:
    """The grammar admits a bare NAME as a condition, so an unguarded enum
    lookup turned a dialect-specific condition into an exception."""
    plan = parse_exec_sql("EXEC SQL WHENEVER MYCOND GO TO H END-EXEC")

    assert plan.whenever_condition == WheneverCondition.NONE


@pytest.mark.parametrize(
    ("condition", "op", "value"),
    [(WheneverCondition.SQLERROR, "<", "0"), (WheneverCondition.NOT_FOUND, "=", "100")],
    ids=["sqlerror", "not-found"],
)
def test_the_synthetic_sqlcode_test_compares_against_a_numeric_literal(
    condition: WheneverCondition, op: str, value: str
) -> None:
    """The lowering compares a relation numerically only when its literal is marked
    numeric, as the bridge marks one; unmarked, SQLCODE = 100 compared characters."""
    from squall.strategy import _sqlcode_if_stmt

    statement = _sqlcode_if_stmt(condition, "ERR-PARA")

    assert statement.condition == {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": "SQLCODE"},
            "op": op,
            "right": {"kind": "lit", "value": value, "numeric": True},
        },
    }
