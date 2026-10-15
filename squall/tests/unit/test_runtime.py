"""The SQL coprocessor's compile spec registers nothing; its runtime installs the builtins."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

import pytest

from interpreter.func_name import FuncName
from interpreter.types.typed_value import TypedValue
from interpreter.vm.builtins import Builtins
from interpreter.vm.vm import VMState
from interpreter.vm.vm_types import BuiltinResult
from squall.backends.sqlite import SqliteBackend
from squall.coprocessor import build_sql_spec
from squall.runtime import install_sql_runtime
from squall.strategy_stores import register

_NAMES = frozenset(
    FuncName(name)
    for name in (
        "__exec_sql",
        "__cics_task_end_hook",
        "__cics_syncpoint_hook",
        "__cics_rollback_hook",
    )
)


def _stand_in(_args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
    return BuiltinResult(value=None)


@pytest.fixture()
def backend():
    conn = sqlite3.connect(":memory:")
    return SqliteBackend(conn)


def test_compile_spec_registers_nothing():
    before = dict(Builtins.TABLE)

    build_sql_spec().make_strategy()

    assert dict(Builtins.TABLE) == before


def test_install_registers_the_four_builtins():
    [register(str(name), _stand_in) for name in _NAMES]

    install_sql_runtime({"DB": SqliteBackend(sqlite3.connect(":memory:"))})

    assert {n for n in Builtins.TABLE if n in _NAMES} == _NAMES
    assert {n for n in _NAMES if Builtins.TABLE[n] is not _stand_in} == _NAMES


def test_install_registers_exec_sql_builtin(backend):
    """Installing the SQL runtime registers '__exec_sql' in Builtins.TABLE."""
    key = FuncName("__exec_sql")
    # Remove any prior registration to test fresh insertion
    Builtins.TABLE.pop(key, None)

    install_sql_runtime(backend)

    assert (
        key in Builtins.TABLE
    ), "__exec_sql must be in Builtins.TABLE after construction"
    assert callable(Builtins.TABLE[key]), "registered value must be callable"


def test_install_registers_task_end_hook(backend):
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


def test_install_registers_syncpoint_and_rollback_hooks(backend):
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
