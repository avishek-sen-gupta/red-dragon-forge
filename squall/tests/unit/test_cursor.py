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


_DECLARE_C1 = "EXEC SQL DECLARE c1 CURSOR FOR SELECT NAME, DEPT FROM STAFF WHERE JOB = 'Mgr' END-EXEC"


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
    builtin, *_ = make_exec_sql_builtin({"SAMPLE": backend})

    def run(sql, *rest):
        builtin([_TV(sql), *(_TV(r) for r in rest)], vm)

    def sqlcode():
        return _zoned_decode(bytes(region[13:22]))

    def pname():
        return _alpha_decode(bytes(region[0:9]))

    def dept():
        return _zoned_decode(bytes(region[9:13]))

    # CONNECT — a run starts disconnected; establish the session first.
    run("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    assert sqlcode() == 0

    # DECLARE — register the cursor's SELECT; no DB work yet.
    run(_DECLARE_C1)
    assert sqlcode() == 0

    # OPEN — run the SELECT, position before the first row.
    run("EXEC SQL OPEN c1 END-EXEC", _DECLARE_C1)
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


def test_fetch_on_undeclared_cursor_is_not_open():
    """FETCH on a cursor name that was never reached by DECLARE CURSOR is
    Db2-faithful SQLCODE -501 (cursor not open) — not the +100 end-of-cursor
    code, which means something else (a *declared* cursor with no more rows,
    or one already CLOSEd)."""
    backend = _backend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    builtin, *_ = make_exec_sql_builtin({"SAMPLE": backend})

    def run(sql, *rest):
        builtin([_TV(sql), *(_TV(r) for r in rest)], vm)

    run("EXEC SQL CONNECT TO SAMPLE END-EXEC")  # a run starts disconnected
    run("EXEC SQL FETCH nope INTO :PNAME, :DEPT END-EXEC")
    assert _zoned_decode(bytes(region[13:22])) == -501


# ── squall-qhi: DECLARE CURSOR recovered from WORKING-STORAGE ────────────────


def test_open_on_a_cursor_declared_via_data_division_exec_sql_returns_sqlcode_0():
    """The load-bearing case (forge-qhi): COTRTLIC declares both its cursors
    in WORKING-STORAGE, so no DECLARE CURSOR statement ever reaches
    PROCEDURE DIVISION or lowers to a __exec_sql call. The bridge now
    recovers it into the raw JSON's "data_division_exec_sql" key (a real
    ProLeap bridge fix, not a squall-side re-parse of raw source);
    squall.data_division_exec_sql.derive_cursors recovers its text, and the
    OPEN carries it -- OPEN must then succeed (SQLCODE 0), not fail with -1
    as it would with no declaration."""
    from squall.data_division_exec_sql import derive_cursors

    bridge_data = {
        "data_division_exec_sql": [
            {
                "section": "WORKING-STORAGE",
                "exec_sql_text": (
                    "EXEC SQL DECLARE C-TR-TYPE-FORWARD CURSOR FOR "
                    "SELECT NAME FROM STAFF WHERE JOB = 'Mgr' END-EXEC"
                ),
            }
        ]
    }
    recovered_cursors = dict(derive_cursors(bridge_data))
    assert "C-TR-TYPE-FORWARD" in recovered_cursors  # sanity: the fixture matches

    backend = _backend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    builtin, *_ = make_exec_sql_builtin({"SAMPLE": backend})

    def run(sql, *rest):
        builtin([_TV(sql), *(_TV(r) for r in rest)], vm)

    def sqlcode():
        return _zoned_decode(bytes(region[13:22]))

    def pname():
        return _alpha_decode(bytes(region[0:9]))

    run("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    assert sqlcode() == 0

    # No DECLARE statement runs here -- it never lowered at all -- yet OPEN
    # must still find the cursor's plan and succeed.
    run(
        "EXEC SQL OPEN C-TR-TYPE-FORWARD END-EXEC",
        recovered_cursors["C-TR-TYPE-FORWARD"],
    )
    assert sqlcode() == 0

    run("EXEC SQL FETCH C-TR-TYPE-FORWARD INTO :PNAME END-EXEC")
    assert sqlcode() == 0 and pname() == "SANDERS"


# ── Db2-faithful -501: "not open" means DECLAREd-but-unopened or CLOSEd too ──


def test_fetch_on_a_declared_but_never_opened_cursor_is_not_open():
    """The canonical -501 case: a cursor DECLAREd but never OPENed. Before
    this fix, a declared-but-unopened cursor fell through to backend.fetch()
    and got the backend's own +100 (its internal _cursors dict has no entry
    either, which is indistinguishable from genuine end-of-data) -- the
    fetch-on-an-undeclared-name case was fixed, but this, the actually
    common one, was not."""
    backend = _backend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    builtin, *_ = make_exec_sql_builtin({"SAMPLE": backend})

    def run(sql, *rest):
        builtin([_TV(sql), *(_TV(r) for r in rest)], vm)

    def sqlcode():
        return _zoned_decode(bytes(region[13:22]))

    run("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    run(_DECLARE_C1)
    # No OPEN c1 here.
    run("EXEC SQL FETCH c1 INTO :PNAME, :DEPT END-EXEC")
    assert sqlcode() == -501


def test_fetch_after_close_is_not_open():
    """FETCH on a cursor that was OPENed and then CLOSEd is also -501, not
    the backend's own end-of-data +100 -- CLOSE removes the name from
    ctx.open_cursors, which FETCH consults before ever reaching the backend."""
    backend = _backend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    builtin, *_ = make_exec_sql_builtin({"SAMPLE": backend})

    def run(sql, *rest):
        builtin([_TV(sql), *(_TV(r) for r in rest)], vm)

    def sqlcode():
        return _zoned_decode(bytes(region[13:22]))

    run("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    run(_DECLARE_C1)
    run("EXEC SQL OPEN c1 END-EXEC", _DECLARE_C1)
    run("EXEC SQL CLOSE c1 END-EXEC")
    assert sqlcode() == 0

    run("EXEC SQL FETCH c1 INTO :PNAME, :DEPT END-EXEC")
    assert sqlcode() == -501


def test_close_on_a_cursor_that_is_not_open_is_not_open():
    """CLOSE itself reports -501 for a cursor that is not currently open --
    a declared-but-unopened cursor, or one already CLOSEd -- rather than the
    unconditional SQLCODE 0 it used to write for any name at all."""
    backend = _backend()
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    builtin, *_ = make_exec_sql_builtin({"SAMPLE": backend})

    def run(sql, *rest):
        builtin([_TV(sql), *(_TV(r) for r in rest)], vm)

    def sqlcode():
        return _zoned_decode(bytes(region[13:22]))

    run("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    run(_DECLARE_C1)
    # Never OPENed.
    run("EXEC SQL CLOSE c1 END-EXEC")
    assert sqlcode() == -501

    # OPEN, then CLOSE twice -- the second CLOSE finds it already not open.
    run("EXEC SQL OPEN c1 END-EXEC", _DECLARE_C1)
    assert sqlcode() == 0
    run("EXEC SQL CLOSE c1 END-EXEC")
    assert sqlcode() == 0
    run("EXEC SQL CLOSE c1 END-EXEC")
    assert sqlcode() == -501
