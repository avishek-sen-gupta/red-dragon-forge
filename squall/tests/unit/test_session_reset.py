"""
tests/unit/test_session_reset.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
reset_session (the builtin make_exec_sql_builtin returns alongside
__exec_sql itself): commits the current connection and closes every
declared cursor, without erroring when disconnected. Models the implicit
SYNCPOINT + cursor-close a real CICS-attached Db2 session gets at task end.
"""

from __future__ import annotations

import sqlite3

from squall.backends.sqlite import SqliteBackend
from squall.binding import _zoned_decode
from squall.builtins.exec_sql import make_exec_sql_builtin
from squall.parser.parse import parse_exec_sql

from interpreter.var_name import VarName
from interpreter.address import Address

# PNAME X(9) @0, DEPT 9(4) ZONED @9, SQLCODE S9(9) ZONED @13 — same layout as
# test_cursor.py, reused for the cursor-close assertion (FETCH's sqlcode).
_LAYOUT = {
    "PNAME": {
        "offset": 0,
        "length": 9,
        "category": "ALPHANUMERIC",
        "total_digits": 9,
        "decimal_digits": 0,
        "signed": False,
    },
    "DEPT": {
        "offset": 9,
        "length": 4,
        "category": "ZONED_DECIMAL",
        "total_digits": 4,
        "decimal_digits": 0,
        "signed": False,
    },
    "SQLCODE": {
        "offset": 13,
        "length": 9,
        "category": "ZONED_DECIMAL",
        "total_digits": 9,
        "decimal_digits": 0,
        "signed": True,
    },
}
_REGION_SIZE = 22


class _Addr:
    def __init__(self, v):
        self.value = v


class _Frame:
    def __init__(self, addr):
        self.local_vars = {VarName("__ws_region"): _Addr(addr)}


class _VM:
    def __init__(self, region, addr="1"):
        self._region = region
        self.data_layout = _LAYOUT
        self._addr = Address(addr)
        self.call_stack = [_Frame(addr)]

    def region_get(self, addr):
        assert isinstance(addr, Address)
        return self._region if addr == self._addr else None


class _TV:
    def __init__(self, v):
        self.value = v


def _backend():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE STAFF (NAME VARCHAR(9), DEPT INTEGER, JOB VARCHAR(5))")
    conn.executemany(
        "INSERT INTO STAFF VALUES (?, ?, ?)",
        [("SANDERS", 20, "Mgr"), ("MARENGHI", 38, "Mgr")],
    )
    conn.commit()
    return SqliteBackend(conn)


class _RecordingBackend:
    """A fake SqlBackend that just records whether commit() was called —
    the real backends' commit() is a one-line passthrough already covered by
    _h_commit's own tests, so this isolates reset_session's own logic (does
    it call commit at all, does it skip calling it when disconnected)."""

    def __init__(self):
        self.committed = False

    def open_cursor(self, name, sql, params):
        raise AssertionError("not used by this test")

    def fetch(self, name):
        raise AssertionError("not used by this test")

    def close(self, name):
        raise AssertionError("not used by this test")

    def execute(self, sql, params):
        raise AssertionError("not used by this test")

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("not used by this test")


def test_reset_session_closes_an_open_cursor():
    """A cursor left OPEN (mid-fetch, more rows remaining) is closed by
    reset_session — a subsequent FETCH on the same name (no re-OPEN) reports
    Db2-faithful SQLCODE -501 (not open), the same code
    test_fetch_on_undeclared_cursor_is_not_open (tests/unit/test_cursor.py)
    reports for a name FETCH never reaches at all: reset_session clears
    ctx.open_cursors (not ctx.cursors, which must survive task end for a
    WORKING-STORAGE DECLARE), so a CLOSEd cursor and a never-OPENed one are
    now indistinguishable to FETCH, exactly as real Db2 makes them."""
    backend = _backend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    plans: list = []
    builtin, reset, *_ = make_exec_sql_builtin({"SAMPLE": backend}, plans, {})

    def run(sql):
        plans.append(parse_exec_sql(sql))
        builtin([_TV(len(plans) - 1)], vm)

    def sqlcode():
        return _zoned_decode(bytes(region[13:22]))

    run("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    run(
        "EXEC SQL DECLARE c1 CURSOR FOR SELECT NAME, DEPT FROM STAFF WHERE JOB = 'Mgr' END-EXEC"
    )
    run("EXEC SQL OPEN c1 END-EXEC")
    run("EXEC SQL FETCH c1 INTO :PNAME, :DEPT END-EXEC")
    assert sqlcode() == 0  # first row fetched fine; a second row remains

    reset([], vm)

    run("EXEC SQL FETCH c1 INTO :PNAME, :DEPT END-EXEC")
    assert sqlcode() == -501  # closed by reset — not "still open, next row"

    # The DECLARE itself must survive task end -- nothing will ever re-DECLARE
    # a WORKING-STORAGE cursor, so ctx.cursors (unlike ctx.open_cursors) is
    # untouched by reset_session. A re-OPEN must still succeed.
    run("EXEC SQL OPEN c1 END-EXEC")
    assert sqlcode() == 0


def test_reset_session_commits_the_current_connection():
    from squall.connector import NamedDbConnector

    backend = _RecordingBackend()
    plans: list = []
    _builtin, reset, *_ = make_exec_sql_builtin(
        {"SAMPLE": backend},
        plans,
        {},
        initial_connector=NamedDbConnector("SAMPLE"),
    )
    assert backend.committed is False
    reset([], vm=None)
    assert backend.committed is True


def test_reset_session_is_a_noop_when_disconnected():
    """No connection ever established -> reset_session must not raise (there
    is nothing to commit or close)."""
    backend = _RecordingBackend()
    plans: list = []
    _builtin, reset, *_ = make_exec_sql_builtin({"SAMPLE": backend}, plans, {})

    reset([], vm=None)  # must not raise

    assert backend.committed is False


class _UowRecordingBackend:
    """Tracks commit/rollback calls and which cursor names were closed —
    isolates the task-end/syncpoint/rollback distinction from a real
    backend's own cursor mechanics."""

    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.closed: list[str] = []

    def open_cursor(self, name, sql, params):
        raise AssertionError("not used by this test")

    def fetch(self, name):
        raise AssertionError("not used by this test")

    def close(self, name):
        self.closed.append(name)

    def execute(self, sql, params):
        raise AssertionError("not used by this test")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _declare_cursor(builtin, plans, vm) -> None:
    from squall.parser.parse import parse_exec_sql

    plans.append(
        parse_exec_sql(
            "EXEC SQL DECLARE c1 CURSOR FOR SELECT 1 FROM SYSIBM.SYSDUMMY1 END-EXEC"
        )
    )
    builtin([_TV(len(plans) - 1)], vm)


def test_syncpoint_commits_without_closing_cursors():
    """Ruling (task-6 brief): SYNCPOINT commits the pending unit of work but
    must NOT close cursors — COTRTLIC opens, fetches and closes every cursor
    within one paragraph inside a single task, so getting this distinction
    wrong breaks its paging."""
    from squall.connector import NamedDbConnector

    backend = _UowRecordingBackend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    plans: list = []
    builtin, _reset, syncpoint, _rollback = make_exec_sql_builtin(
        {"SAMPLE": backend},
        plans,
        {},
        initial_connector=NamedDbConnector("SAMPLE"),
    )
    _declare_cursor(builtin, plans, vm)

    syncpoint([], vm=None)

    assert backend.committed is True
    assert backend.rolled_back is False
    assert backend.closed == []


def test_task_end_commits_and_closes_cursors():
    """The task-end hook (RETURN), unlike syncpoint, DOES close every
    declared cursor — the two must not collapse into the same behaviour."""
    from squall.connector import NamedDbConnector

    backend = _UowRecordingBackend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    plans: list = []
    builtin, reset, _syncpoint, _rollback = make_exec_sql_builtin(
        {"SAMPLE": backend},
        plans,
        {},
        initial_connector=NamedDbConnector("SAMPLE"),
    )
    _declare_cursor(builtin, plans, vm)

    reset([], vm=None)

    assert backend.committed is True
    assert backend.closed == ["c1"]


def test_rollback_hook_rolls_back_and_closes_cursors():
    """__cics_rollback_hook (SYNCPOINT ROLLBACK, or a composed on_abend
    callable) undoes the unit of work instead of committing it, and still
    closes every cursor."""
    from squall.connector import NamedDbConnector

    backend = _UowRecordingBackend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    plans: list = []
    builtin, _reset, _syncpoint, rollback = make_exec_sql_builtin(
        {"SAMPLE": backend},
        plans,
        {},
        initial_connector=NamedDbConnector("SAMPLE"),
    )
    _declare_cursor(builtin, plans, vm)

    rollback([], vm=None)

    assert backend.rolled_back is True
    assert backend.committed is False
    assert backend.closed == ["c1"]


def test_reset_session_returns_a_builtin_result():
    """reset_session has the standard RedDragon builtin signature (it is
    registered directly into Builtins.TABLE and dispatched via
    CallFunction, same as __exec_sql itself)."""
    from interpreter.vm.vm_types import BuiltinResult

    backend = _RecordingBackend()
    plans: list = []
    _builtin, reset, *_ = make_exec_sql_builtin({"SAMPLE": backend}, plans, {})

    result = reset([], vm=None)

    assert isinstance(result, BuiltinResult)
    assert result.value is None
