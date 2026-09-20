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
from squall.parser.sql_model import Kind
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
def strategy(backend):
    return SqlLoweringStrategy(backend, {})


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


def test_lower_parses_once_into_pool(strategy):
    """The directive is parsed at lower() time into the strategy's plan pool;
    the Const carries only the integer pool index (a primitive), so the builtin
    never re-parses at run time and no object travels through the IR."""
    from squall.parser.parse import ParsedSql, HostVar

    text = "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT END-EXEC"
    stmt = ExecSqlStatement(text=text)
    ctx = _FakeEmitContext()

    strategy.lower(ctx, stmt, materialised=None)

    # The Const carries the pool index (int 0 for the first lowered statement).
    const_insts = [i for i in ctx.emitted if isinstance(i, Const)]
    assert len(const_insts) == 1
    assert const_insts[0].value == 0

    # The parsed plan lives in the strategy's constant pool, parsed exactly once.
    assert len(strategy._plans) == 1
    plan = strategy._plans[0]
    assert isinstance(plan, ParsedSql)
    assert plan.kind is Kind.SELECT_INTO
    assert plan.query == "SELECT ACCT_BAL FROM ACCOUNT"
    assert plan.out_vars == (HostVar("WS-BAL", None),)


def test_strategy_registers_exec_sql_builtin(backend):
    """Constructing SqlLoweringStrategy registers '__exec_sql' in Builtins.TABLE."""
    key = FuncName("__exec_sql")
    # Remove any prior registration to test fresh insertion
    Builtins.TABLE.pop(key, None)

    SqlLoweringStrategy(backend, {})

    assert (
        key in Builtins.TABLE
    ), "__exec_sql must be in Builtins.TABLE after construction"
    assert callable(Builtins.TABLE[key]), "registered value must be callable"


def test_strategy_registers_task_end_hook(backend):
    """Constructing SqlLoweringStrategy claims the generic, cicada-owned
    __cics_task_end_hook extension point — squall's session reset (commit +
    close every cursor) runs whenever a composed CICS runtime signals task
    end, with neither package importing the other."""
    key = FuncName("__cics_task_end_hook")
    previous = Builtins.TABLE.get(key)
    try:
        Builtins.TABLE.pop(key, None)

        SqlLoweringStrategy(backend, {})

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
    """Constructing SqlLoweringStrategy also claims __cics_syncpoint_hook and
    __cics_rollback_hook — the same name-convention composition as
    __cics_task_end_hook, so EXEC CICS SYNCPOINT / SYNCPOINT ROLLBACK reach
    squall without cicada ever naming it (task-6 brief)."""
    keys = (FuncName("__cics_syncpoint_hook"), FuncName("__cics_rollback_hook"))
    previous = {key: Builtins.TABLE.get(key) for key in keys}
    try:
        for key in keys:
            Builtins.TABLE.pop(key, None)

        SqlLoweringStrategy(backend, {})

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


def test_preprocess_program_dict_derives_varchar_field_meta(strategy):
    """With no sidecar at all, preprocess_program_dict must still populate
    field_meta for a DCLGEN VARCHAR group found in the raw bridge JSON."""
    strategy.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)

    assert strategy._field_meta["DCL-TR-DESCRIPTION"]["category"] == "VARCHAR"
    assert strategy._field_meta["DCL-TR-DESCRIPTION"]["length"] == 50


def test_sidecar_field_meta_wins_over_derived_on_conflict(backend):
    """A sidecar is an explicit statement; derivation is only an inference.
    Where both describe the same host var, the sidecar's category must win."""
    sidecar = {"DCL-TR-DESCRIPTION": {"category": "ALPHANUMERIC", "length": 999}}
    strat = SqlLoweringStrategy(backend, sidecar)

    strat.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)

    assert strat._field_meta["DCL-TR-DESCRIPTION"] == {
        "category": "ALPHANUMERIC",
        "length": 999,
    }


def test_field_meta_is_immutable_to_external_consumers(strategy):
    """The publicly held field_meta stays a MappingProxyType — read-only —
    even after preprocess_program_dict has populated it."""
    strategy.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)

    with pytest.raises(TypeError):
        strategy._field_meta["DCL-TR-DESCRIPTION"] = {}  # type: ignore[index]


def test_derived_field_meta_reaches_the_already_registered_builtin(
    backend, monkeypatch
):
    """The __exec_sql builtin is registered at construction time, BEFORE
    preprocess_program_dict ever runs (compile_program builds every strategy
    before any preprocess_program_dict call) -- so the Mapping object handed
    to make_exec_sql_builtin must be the SAME live view preprocess_program_dict
    later updates, not a snapshot frozen at construction. This is the exact
    propagation gap that made the correct VARCHAR codec unreachable."""
    from squall import strategy as strategy_module

    captured: dict = {}
    original_factory = strategy_module.make_exec_sql_builtin

    def spy(connections, plans, field_meta, *args, **kwargs):
        captured["field_meta"] = field_meta
        return original_factory(connections, plans, field_meta, *args, **kwargs)

    monkeypatch.setattr(strategy_module, "make_exec_sql_builtin", spy)

    strat = SqlLoweringStrategy(backend, {})
    assert "DCL-TR-DESCRIPTION" not in captured["field_meta"]

    strat.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)

    # Same object the builtin factory was given, now carrying the derived entry.
    assert captured["field_meta"] is strat._field_meta
    assert captured["field_meta"]["DCL-TR-DESCRIPTION"]["category"] == "VARCHAR"


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


def test_preprocess_program_dict_derives_cursors(strategy):
    """A DECLARE CURSOR the bridge recovered from outside PROCEDURE DIVISION
    must reach the strategy's own cursor store -- the store OPEN's handler
    reads at run time."""
    strategy.preprocess_program_dict(_BRIDGE_WORKING_STORAGE_DECLARE)

    assert "C-TR-TYPE-FORWARD" in strategy._cursors_store


def test_derived_cursors_reach_the_already_registered_builtin(backend, monkeypatch):
    """Same propagation gap as field_meta: the __exec_sql builtin is built at
    construction time, before preprocess_program_dict ever runs, so the dict
    handed to make_exec_sql_builtin as `cursors=` must be the SAME live
    object preprocess_program_dict later updates, not a snapshot."""
    from squall import strategy as strategy_module

    captured: dict = {}
    original_factory = strategy_module.make_exec_sql_builtin

    def spy(connections, plans, field_meta, *args, **kwargs):
        captured["cursors"] = kwargs.get("cursors")
        return original_factory(connections, plans, field_meta, *args, **kwargs)

    monkeypatch.setattr(strategy_module, "make_exec_sql_builtin", spy)

    strat = SqlLoweringStrategy(backend, {})
    assert "C-TR-TYPE-FORWARD" not in captured["cursors"]

    strat.preprocess_program_dict(_BRIDGE_WORKING_STORAGE_DECLARE)

    assert captured["cursors"] is strat._cursors_store
    assert "C-TR-TYPE-FORWARD" in captured["cursors"]


def test_one_spec_keeps_every_programs_plans_reachable(backend):
    """forge-2xy. Only ONE ``__exec_sql`` builtin can live in the
    process-global ``Builtins.TABLE``, and ``compile_program`` builds a fresh
    strategy per program -- so the last program compiled from a spec supplies
    the builtin every EARLIER program's lowered code also calls. With
    per-strategy plan pools the first program's ``Const(0)`` then addresses
    the second program's plan 0: same index, different SQL, no error.

    Verified by execution AND verified to fail without the fix: reverting
    ``build_sql_spec``'s ``stores=stores`` makes the second strategy restart
    at index 0, so ``indices == (0, 0)`` and the surviving pool holds only
    T2's statement.
    """
    from squall.coprocessor import build_sql_spec

    spec = build_sql_spec({"X": backend})

    # Any, not SqlLoweringStrategy: make_strategy is typed as the RedDragon
    # protocol, and these assertions reach for the private stores behind it.
    first: Any = spec.make_strategy()
    second: Any = spec.make_strategy()
    contexts = (_FakeEmitContext(), _FakeEmitContext())
    for strat, ctx, table in ((first, contexts[0], "T1"), (second, contexts[1], "T2")):
        strat.lower(
            ctx,
            ExecSqlStatement(
                text=f"EXEC SQL SELECT A INTO :WS-A FROM {table} END-EXEC"
            ),
            materialised=None,
        )

    indices = tuple(
        next(i.value for i in ctx.emitted if isinstance(i, Const)) for ctx in contexts
    )
    assert indices == (0, 1)
    # The pool the LAST-registered builtin closes over must still resolve the
    # FIRST program's index to the first program's own statement.
    assert second._plans[indices[0]].query == "SELECT A FROM T1"
    assert second._plans[indices[1]].query == "SELECT A FROM T2"


def test_one_spec_shares_the_cursor_store_across_programs(backend):
    """forge-2xy, the cursor half: COTRTLIC's ``OPEN C-TR-TYPE-FORWARD``
    resolves against whichever cursor store the surviving builtin holds, so a
    second SQL program compiled from the same spec must not hand that builtin
    a store missing the first program's DECLAREs."""
    from squall.coprocessor import build_sql_spec

    spec = build_sql_spec({"X": backend})
    first: Any = spec.make_strategy()
    second: Any = spec.make_strategy()
    first.preprocess_program_dict(_BRIDGE_WORKING_STORAGE_DECLARE)

    assert second._cursors_store is first._cursors_store
    assert "C-TR-TYPE-FORWARD" in second._cursors_store
