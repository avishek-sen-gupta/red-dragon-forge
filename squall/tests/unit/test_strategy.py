"""
tests/unit/test_strategy.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for squall.strategy — ``SqlLoweringStrategy``.

Verifies:
- ``handles(ExecSqlStatement)`` is True; ``handles(<other>)`` is False.
- ``lower(...)`` emits a single ``CallFunction`` targeting ``__exec_sql``
  whose single operand carries the verbatim text.
- Installing the SQL runtime registers ``__exec_sql`` in ``Builtins.TABLE``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

import pytest

from squall.backends.sqlite import SqliteBackend
from squall.parser.sql_model import Kind
from squall.runtime import install_sql_runtime
from squall.strategy import SqlLoweringStrategy

# ── Imports from vendored red-dragon ─────────────────────────────────────────

from squall.statements import ExecSqlStatement
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

    def emit_inst(self, inst: Any, *, span=None) -> None:
        self.emitted.append(inst)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def backend():
    conn = sqlite3.connect(":memory:")
    return SqliteBackend(conn)


@pytest.fixture()
def strategy():
    return SqlLoweringStrategy()


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
    text = (
        "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = 1 END-EXEC"
    )
    stmt = ExecSqlStatement(text=text)
    ctx = _FakeEmitContext()

    strategy.lower(ctx, stmt, materialised=None)

    # There should be at least two instructions: Const + CallFunction
    call_insts = [i for i in ctx.emitted if isinstance(i, CallFunction)]
    assert len(call_insts) == 1, f"Expected 1 CallFunction, got {len(call_insts)}"

    call = call_insts[0]
    assert call.func_name == FuncName(
        "__exec_sql"
    ), f"func_name should be __exec_sql, got {call.func_name!r}"
    assert len(call.args) == 1, f"Expected 1 arg, got {len(call.args)}"


def test_strategy_registers_exec_sql_builtin(backend):
    """Installing the SQL runtime registers '__exec_sql' in Builtins.TABLE."""
    key = FuncName("__exec_sql")
    # Remove any prior registration to test fresh insertion
    Builtins.TABLE.pop(key, None)

    install_sql_runtime(backend)

    assert (
        key in Builtins.TABLE
    ), "__exec_sql must be in Builtins.TABLE after construction"
    assert callable(Builtins.TABLE[key]), "registered value must be callable"


def test_strategy_registers_task_end_hook(backend):
    """Installing the SQL runtime claims the generic, cicada-owned
    __cics_task_end_hook extension point — squall's session reset (commit +
    close every cursor) runs whenever a composed CICS runtime signals task
    end, with neither package importing the other."""
    key = FuncName("__cics_task_end_hook")
    previous = Builtins.TABLE.get(key)
    try:
        Builtins.TABLE.pop(key, None)

        install_sql_runtime(backend)

        assert key in Builtins.TABLE
        assert callable(Builtins.TABLE[key])
        result = Builtins.TABLE[key]([], vm=None)
        assert result.value is None
    finally:
        if previous is None:
            Builtins.TABLE.pop(key, None)
        else:
            Builtins.TABLE[key] = previous


def test_strategy_registers_syncpoint_and_rollback_hooks(backend):
    """Installing the SQL runtime also claims __cics_syncpoint_hook and
    __cics_rollback_hook — the same name-convention composition as
    __cics_task_end_hook, so EXEC CICS SYNCPOINT / SYNCPOINT ROLLBACK reach
    squall without cicada ever naming it (task-6 brief)."""
    keys = (FuncName("__cics_syncpoint_hook"), FuncName("__cics_rollback_hook"))
    previous = {key: Builtins.TABLE.get(key) for key in keys}
    try:
        for key in keys:
            Builtins.TABLE.pop(key, None)

        install_sql_runtime(backend)

        for key in keys:
            assert key in Builtins.TABLE
            assert callable(Builtins.TABLE[key])
            result = Builtins.TABLE[key]([], vm=None)
            assert result.value is None
    finally:
        for key, value in previous.items():
            if value is None:
                Builtins.TABLE.pop(key, None)
            else:
                Builtins.TABLE[key] = value


def test_preprocess_program_dict_returns_data_unchanged(strategy):
    """preprocess_program_dict has a real side effect now (see the tests
    below) but still returns *data* itself, untransformed -- its effect is
    entirely the field_meta-store merge, never a rewrite of the bridge dict."""
    data = {"key": "value"}
    result = strategy.preprocess_program_dict(data)
    assert result is data


# ── DCLGEN VARCHAR field_meta derivation (forge-yuo) ─────────────────────────

_BRIDGE_VARCHAR_GROUP = {
    "data_fields": [
        {
            "name": "DCL-TR-DESCRIPTION",
            "level": 10,
            "pic": "",
            "usage": "DISPLAY",
            "children": [
                {
                    "name": "DCL-TR-DESCRIPTION-LEN",
                    "level": 49,
                    "pic": "S9(4)",
                    "usage": "COMP",
                },
                {
                    "name": "DCL-TR-DESCRIPTION-TEXT",
                    "level": 49,
                    "pic": "X(50)",
                    "usage": "DISPLAY",
                },
            ],
        }
    ]
}


def test_on_procedure_entry_is_noop(strategy):
    ctx = _FakeEmitContext()
    strategy.on_procedure_entry(ctx, materialised=None)
    assert ctx.emitted == []


# ── DECLARE CURSOR recovered from WORKING-STORAGE (forge-qhi) ────────────────

_BRIDGE_WORKING_STORAGE_DECLARE = {
    "data_division_exec_sql": [
        {
            "section": "WORKING-STORAGE",
            "exec_sql_text": (
                "EXEC SQL DECLARE C-TR-TYPE-FORWARD CURSOR FOR "
                "SELECT TR_TYPE FROM CARDDEMO.TRANSACTION_TYPE END-EXEC"
            ),
        }
    ]
}


def _call_args(ctx) -> list:
    consts = {i.result_reg: i.value for i in ctx.emitted if isinstance(i, Const)}
    (call,) = [i for i in ctx.emitted if isinstance(i, CallFunction)]
    return [consts[a] for a in call.args]


def test_a_statement_carries_its_text(strategy):
    text = "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT END-EXEC"
    ctx = _FakeEmitContext()
    strategy.lower(ctx, ExecSqlStatement(text=text), materialised=None)
    assert _call_args(ctx) == [text]


def test_an_open_carries_its_working_storage_declaration(strategy):
    strategy.preprocess_program_dict(_BRIDGE_WORKING_STORAGE_DECLARE)
    ctx = _FakeEmitContext()
    open_text = "EXEC SQL OPEN C-TR-TYPE-FORWARD END-EXEC"
    strategy.lower(ctx, ExecSqlStatement(text=open_text), materialised=None)
    declaration = _BRIDGE_WORKING_STORAGE_DECLARE["data_division_exec_sql"][0][
        "exec_sql_text"
    ]
    assert _call_args(ctx) == [open_text, declaration]


def test_a_procedure_declare_emits_nothing_and_reaches_its_open(strategy):
    declare = "EXEC SQL DECLARE C1 CURSOR FOR SELECT X FROM T END-EXEC"
    open_text = "EXEC SQL OPEN C1 END-EXEC"
    strategy.preprocess_program_dict({})
    declare_ctx, open_ctx = _FakeEmitContext(), _FakeEmitContext()
    strategy.lower(declare_ctx, ExecSqlStatement(text=declare), materialised=None)
    strategy.lower(open_ctx, ExecSqlStatement(text=open_text), materialised=None)
    assert (declare_ctx.emitted, _call_args(open_ctx)) == ([], [open_text, declare])


def test_a_varchar_host_variable_carries_its_shape(strategy):
    strategy.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)
    text = "EXEC SQL SELECT D INTO :DCL-TR-DESCRIPTION FROM T END-EXEC"
    ctx = _FakeEmitContext()
    strategy.lower(ctx, ExecSqlStatement(text=text), materialised=None)
    assert _call_args(ctx) == [
        text,
        "DCL-TR-DESCRIPTION",
        "DCL-TR-DESCRIPTION-LEN",
        "DCL-TR-DESCRIPTION-TEXT",
    ]


def test_an_open_using_carries_the_shapes_of_its_own_host_variables(strategy):
    strategy.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)
    declare = "EXEC SQL DECLARE C1 CURSOR FOR SELECT X FROM T WHERE Y = :WS-Y END-EXEC"
    open_text = "EXEC SQL OPEN C1 USING :DCL-TR-DESCRIPTION END-EXEC"
    strategy.lower(
        _FakeEmitContext(), ExecSqlStatement(text=declare), materialised=None
    )
    ctx = _FakeEmitContext()
    strategy.lower(ctx, ExecSqlStatement(text=open_text), materialised=None)
    assert _call_args(ctx) == [
        open_text,
        declare,
        "DCL-TR-DESCRIPTION",
        "DCL-TR-DESCRIPTION-LEN",
        "DCL-TR-DESCRIPTION-TEXT",
    ]


def test_programs_lowered_by_one_strategy_keep_their_own_shapes(strategy):
    text = "EXEC SQL SELECT D INTO :DCL-TR-DESCRIPTION FROM T END-EXEC"
    strategy.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)
    first = _FakeEmitContext()
    strategy.lower(first, ExecSqlStatement(text=text), materialised=None)
    strategy.preprocess_program_dict({})
    second = _FakeEmitContext()
    strategy.lower(second, ExecSqlStatement(text=text), materialised=None)
    assert (len(_call_args(first)), _call_args(second)) == (4, [text])


def test_an_undeclared_open_carries_only_its_own_text(strategy):
    strategy.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)
    open_text = "EXEC SQL OPEN NOSUCH USING :DCL-TR-DESCRIPTION END-EXEC"
    ctx = _FakeEmitContext()
    strategy.lower(ctx, ExecSqlStatement(text=open_text), materialised=None)
    assert _call_args(ctx) == [open_text]


def test_a_cursor_is_found_whatever_the_case_it_is_written_in(strategy):
    declare = "EXEC SQL DECLARE c1 CURSOR FOR SELECT X FROM T END-EXEC"
    open_text = "EXEC SQL OPEN C1 END-EXEC"
    strategy.preprocess_program_dict(
        {
            "data_division_exec_sql": [
                {
                    "section": "WORKING-STORAGE",
                    "exec_sql_text": "EXEC SQL DECLARE ws1 CURSOR FOR SELECT Y FROM T END-EXEC",
                }
            ]
        }
    )
    strategy.lower(
        _FakeEmitContext(), ExecSqlStatement(text=declare), materialised=None
    )
    procedure, working_storage = _FakeEmitContext(), _FakeEmitContext()
    strategy.lower(procedure, ExecSqlStatement(text=open_text), materialised=None)
    strategy.lower(
        working_storage,
        ExecSqlStatement(text="EXEC SQL OPEN WS1 END-EXEC"),
        materialised=None,
    )
    assert (_call_args(procedure)[1], len(_call_args(working_storage))) == (declare, 2)
