"""Installing the SQL runtime returns its builtins and its unit-of-work hooks; it writes no shared table."""

from __future__ import annotations

import sqlite3

import pytest

from interpreter.func_name import FuncName
from squall.backends.sqlite import SqliteBackend
from squall.runtime import install_sql_runtime


@pytest.fixture()
def backend():
    conn = sqlite3.connect(":memory:")
    return SqliteBackend(conn)


def test_install_returns_exec_sql_as_its_only_entry(backend):
    runtime = install_sql_runtime({"DB": backend})

    assert set(runtime.entries) == {FuncName("__exec_sql")}
    assert callable(runtime.entries[FuncName("__exec_sql")])
    assert not any(str(name).startswith("__cics_") for name in runtime.entries)


def test_install_returns_the_three_unit_of_work_hooks(backend):
    """The session reset (commit + close every cursor), the syncpoint (commit)
    and the rollback (roll back + close every cursor) come back as plain
    callables for a composer to hand to a CICS runtime; squall names none of
    the CICS hook builtins itself."""
    runtime = install_sql_runtime({"DB": backend})

    hooks = (runtime.reset_session, runtime.syncpoint, runtime.rollback)
    assert [hook([], None).value for hook in hooks] == [None, None, None]
    assert len({id(hook) for hook in hooks}) == 3
