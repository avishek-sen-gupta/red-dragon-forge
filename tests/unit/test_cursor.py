"""
tests/unit/test_cursor.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
The EXEC SQL cursor flow through the __exec_sql builtin:
DECLARE c CURSOR FOR <select>  ->  OPEN c  ->  FETCH c INTO :a,:b (loop)  ->  CLOSE c.

DECLARE/OPEN/FETCH/CLOSE map onto the backend's open_cursor/fetch/close surface;
FETCH binds the row into the host vars; end-of-cursor sets SQLCODE 100.
"""

from __future__ import annotations

import sqlite3

from squall.backends.sqlite import SqliteBackend
from squall.binding import _zoned_decode, _alpha_decode
from squall.builtins.exec_sql import make_exec_sql_builtin
from squall.parser.parse import parse_exec_sql

from interpreter.var_name import VarName
from interpreter.address import Address

# PNAME X(9) @0, DEPT 9(4) ZONED @9, SQLCODE S9(9) ZONED @13
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
        [("SANDERS", 20, "Mgr"), ("MARENGHI", 38, "Mgr"), ("NGAN", 15, "Clerk")],
    )
    conn.commit()
    return SqliteBackend(conn)


def test_cursor_declare_open_fetch_close():
    backend = _backend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    plans: list = []
    builtin = make_exec_sql_builtin(backend, plans)

    def run(sql):
        plans.append(parse_exec_sql(sql))
        builtin([_TV(len(plans) - 1)], vm)

    def sqlcode():
        return _zoned_decode(bytes(region[13:22]))

    def pname():
        return _alpha_decode(bytes(region[0:9]))

    def dept():
        return _zoned_decode(bytes(region[9:13]))

    # DECLARE — register the cursor's SELECT; no DB work yet.
    run(
        "EXEC SQL DECLARE c1 CURSOR FOR SELECT NAME, DEPT FROM STAFF WHERE JOB = 'Mgr' END-EXEC"
    )
    assert sqlcode() == 0

    # OPEN — run the SELECT, position before the first row.
    run("EXEC SQL OPEN c1 END-EXEC")
    assert sqlcode() == 0

    # FETCH ×2 — first two managers, in order, into PNAME/DEPT.
    run("EXEC SQL FETCH c1 INTO :PNAME, :DEPT END-EXEC")
    assert sqlcode() == 0 and pname() == "SANDERS" and dept() == 20

    run("EXEC SQL FETCH c1 INTO :PNAME, :DEPT END-EXEC")
    assert sqlcode() == 0 and pname() == "MARENGHI" and dept() == 38

    # FETCH past the end — SQLCODE 100, host vars untouched (NGAN is a Clerk, excluded).
    run("EXEC SQL FETCH c1 INTO :PNAME, :DEPT END-EXEC")
    assert sqlcode() == 100 and pname() == "MARENGHI"

    # CLOSE.
    run("EXEC SQL CLOSE c1 END-EXEC")
    assert sqlcode() == 0


def test_fetch_on_unopened_cursor_is_end():
    """FETCH on a cursor that was never opened reports end-of-cursor (100)."""
    backend = _backend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    plans: list = []
    builtin = make_exec_sql_builtin(backend, plans)
    plans.append(parse_exec_sql("EXEC SQL FETCH nope INTO :PNAME, :DEPT END-EXEC"))
    builtin([_TV(0)], vm)
    assert _zoned_decode(bytes(region[13:22])) == 100
