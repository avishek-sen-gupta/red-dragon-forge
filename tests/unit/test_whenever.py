"""
tests/unit/test_whenever.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
EXEC SQL WHENEVER <condition> <action> — a precompiler directive that squall
surfaces on ParsedSql and the strategy applies as lexically-scoped automatic
SQLCODE branching. Slice 1: SQLERROR / NOT FOUND with CONTINUE / GO TO.
"""

from __future__ import annotations

from squall.parser.parse import parse_exec_sql
from squall.parser.sql_model import Kind


def test_parse_whenever_sqlerror_goto():
    p = parse_exec_sql("EXEC SQL WHENEVER SQLERROR GOTO ERR-EXIT END-EXEC")
    assert p.kind is Kind.WHENEVER
    assert p.whenever_condition == "SQLERROR"
    assert p.whenever_action == "GOTO"
    assert p.whenever_target == "ERR-EXIT"


def test_parse_whenever_go_to_two_words():
    p = parse_exec_sql("EXEC SQL WHENEVER SQLERROR GO TO ERR-EXIT END-EXEC")
    assert p.whenever_action == "GOTO"
    assert p.whenever_target == "ERR-EXIT"


def test_parse_whenever_not_found_continue():
    p = parse_exec_sql("EXEC SQL WHENEVER NOT FOUND CONTINUE END-EXEC")
    assert p.kind is Kind.WHENEVER
    assert p.whenever_condition == "NOT FOUND"
    assert p.whenever_action == "CONTINUE"
    assert p.whenever_target is None


def test_parse_non_whenever_has_no_whenever_fields():
    p = parse_exec_sql("EXEC SQL SELECT a INTO :x FROM t END-EXEC")
    assert p.whenever_condition is None
    assert p.whenever_action is None
    assert p.whenever_target is None


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


class _NullBackend:
    """A backend whose execute always fails (SQLCODE -1) — enough to compile."""

    def execute(self, sql, params):
        from squall.backend import SqlResult

        return SqlResult(rows=(), rowcount=0, sqlcode=-1)

    def open_cursor(self, name, sql, params):  # pragma: no cover - unused here
        pass

    def fetch(self, name):  # pragma: no cover - unused here
        from squall.backend import SqlResult

        return SqlResult(rows=(), rowcount=0, sqlcode=100)

    def close(self, name):  # pragma: no cover - unused here
        pass

    def commit(self):  # pragma: no cover - unused here
        pass

    def rollback(self):  # pragma: no cover - unused here
        pass


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
    _frontend, linked = compile_cobol(
        _PROGRAM_GOTO, jar, {"SAMPLE": _NullBackend()}, copybook_dirs=[]
    )
    assert any(
        isinstance(i, BranchIf) for i in linked.merged_ir
    ), "expected a conditional branch from the synthetic WHENEVER IF/GO TO"
