"""
tests/unit/test_strategy.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for squall.strategy — ``SqlLoweringStrategy``.

Verifies:
- ``handles(ExecSqlStatement)`` is True; ``handles(<other>)`` is False.
- ``lower(...)`` emits a single ``CallFunction`` targeting ``__exec_sql``
  whose single operand carries the verbatim text.
- Constructing the strategy registers ``__exec_sql`` in ``Builtins.TABLE``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

import pytest

from squall.backends.sqlite import SqliteBackend
from squall.strategy import SqlLoweringStrategy

# ── Imports from vendored red-dragon ─────────────────────────────────────────

from interpreter.cobol.cobol_statements import ExecSqlStatement
from interpreter.func_name import FuncName
from interpreter.instructions import CallFunction, Const
from interpreter.vm.builtins import Builtins


# ── Minimal fake EmitContext ──────────────────────────────────────────────────


@dataclass
class _FakeRegister:
    """Minimal register stub."""

    _id: int

    def __hash__(self):
        return hash(self._id)

    def __eq__(self, other):
        return isinstance(other, _FakeRegister) and self._id == other._id


class _FakeEmitContext:
    """Minimal duck-typed EmitContext that records emitted instructions."""

    def __init__(self):
        self._counter = 0
        self.emitted: list[Any] = []

    def fresh_reg(self) -> _FakeRegister:
        self._counter += 1
        return _FakeRegister(self._counter)

    def emit_inst(self, inst: Any) -> None:
        self.emitted.append(inst)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def backend():
    conn = sqlite3.connect(":memory:")
    return SqliteBackend(conn)


@pytest.fixture()
def strategy(backend):
    return SqlLoweringStrategy(backend)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_handles_exec_sql_statement(strategy):
    stmt = ExecSqlStatement(
        text="EXEC SQL SELECT 1 INTO :WS-X FROM SYSIBM.SYSDUMMY1 END-EXEC"
    )
    assert strategy.handles(stmt) is True


def test_handles_returns_false_for_other_stmt(strategy):
    class _OtherStmt:
        pass

    assert strategy.handles(_OtherStmt()) is False


def test_lower_emits_call_function(strategy):
    """lower() must emit exactly one CallFunction targeting '__exec_sql'."""
    text = "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = 1 END-EXEC"
    stmt = ExecSqlStatement(text=text)
    ctx = _FakeEmitContext()

    strategy.lower(ctx, stmt, materialised=None)

    # There should be at least two instructions: Const + CallFunction
    call_insts = [i for i in ctx.emitted if isinstance(i, CallFunction)]
    assert len(call_insts) == 1, f"Expected 1 CallFunction, got {len(call_insts)}"

    call = call_insts[0]
    assert call.func_name == FuncName("__exec_sql"), (
        f"func_name should be __exec_sql, got {call.func_name!r}"
    )
    assert len(call.args) == 1, f"Expected 1 arg, got {len(call.args)}"


def test_lower_const_carries_verbatim_text(strategy):
    """The Const instruction preceding the CallFunction holds the raw text."""
    text = "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT END-EXEC"
    stmt = ExecSqlStatement(text=text)
    ctx = _FakeEmitContext()

    strategy.lower(ctx, stmt, materialised=None)

    const_insts = [i for i in ctx.emitted if isinstance(i, Const)]
    assert len(const_insts) == 1
    assert const_insts[0].value == text, (
        f"Const value mismatch: expected {text!r}, got {const_insts[0].value!r}"
    )


def test_strategy_registers_exec_sql_builtin(backend):
    """Constructing SqlLoweringStrategy registers '__exec_sql' in Builtins.TABLE."""
    key = FuncName("__exec_sql")
    # Remove any prior registration to test fresh insertion
    Builtins.TABLE.pop(key, None)

    SqlLoweringStrategy(backend)

    assert key in Builtins.TABLE, "__exec_sql must be in Builtins.TABLE after construction"
    assert callable(Builtins.TABLE[key]), "registered value must be callable"


def test_preprocess_program_dict_is_noop(strategy):
    data = {"key": "value"}
    result = strategy.preprocess_program_dict(data)
    assert result is data


def test_on_procedure_entry_is_noop(strategy):
    ctx = _FakeEmitContext()
    strategy.on_procedure_entry(ctx, materialised=None)
    assert ctx.emitted == []
