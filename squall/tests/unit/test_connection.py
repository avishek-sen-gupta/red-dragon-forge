"""
tests/unit/test_connection.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Faithful CONNECT: registry routing + per-run connection lifecycle (squall-yml).
"""

from __future__ import annotations

import sqlite3

from interpreter.address import Address
from interpreter.var_name import VarName

from squall.backends.sqlite import SqliteBackend
from squall.binding import _zoned_decode, _zoned_encode
from squall.builtins.exec_sql import make_exec_sql_builtin
from squall.connector import NamedDbConnector, NullDbConnector
from squall.parser.parse import HostVar, parse_exec_sql
from squall.parser.sql_model import (
    ConnectReset,
    ConnectTo,
    HostVarDb,
    Kind,
    LiteralDb,
)


def test_parse_connect_to_literal():
    p = parse_exec_sql("EXEC SQL CONNECT TO sample END-EXEC")
    assert p.kind is Kind.CONNECT
    assert p.connect == ConnectTo(LiteralDb("SAMPLE"))  # DB2 upper-cases db names


def test_parse_connect_to_hostvar():
    p = parse_exec_sql("EXEC SQL CONNECT TO :dbname USER :u USING :p END-EXEC")
    assert p.connect == ConnectTo(HostVarDb(HostVar("dbname", None)))


def test_parse_connect_to_literal_with_creds_ignores_creds():
    # The testbed double-CONNECT idiom: literal db + USER/USING creds. The creds
    # surface in in_vars but the target is the literal, and creds are unread.
    p = parse_exec_sql("EXEC SQL CONNECT TO sample USER :userid USING :passwd END-EXEC")
    assert p.connect == ConnectTo(LiteralDb("SAMPLE"))


def test_parse_connect_reset():
    p = parse_exec_sql("EXEC SQL CONNECT RESET END-EXEC")
    assert p.connect == ConnectReset()


def test_parse_set_connection():
    p = parse_exec_sql("EXEC SQL SET CONNECTION db2 END-EXEC")
    assert p.kind is Kind.SET_CONNECTION
    assert p.connect == ConnectTo(LiteralDb("DB2"))


def test_parse_disconnect():
    p = parse_exec_sql("EXEC SQL DISCONNECT db2 END-EXEC")
    assert p.kind is Kind.DISCONNECT
    assert p.connect == ConnectTo(LiteralDb("DB2"))


# ── Runtime lifecycle ─────────────────────────────────────────────────────────
# Faithful CONNECT: a run starts disconnected; data statements route through the
# current connection and report -1024 when there is none. Minimal fake VM, same
# contract as test_builtin.py (local_vars keyed by VarName, regions by Address).

# WS-ID (zoned 4 @0), SQLCODE (zoned signed 9 @4); region size 13.
_LAYOUT = {
    "WS-ID": {
        "offset": 0,
        "length": 4,
        "category": "ZONED_DECIMAL",
        "total_digits": 4,
        "decimal_digits": 0,
        "signed": False,
    },
    "SQLCODE": {
        "offset": 4,
        "length": 9,
        "category": "ZONED_DECIMAL",
        "total_digits": 9,
        "decimal_digits": 0,
        "signed": True,
    },
}
_REGION_SIZE = 13


class _Addr:
    def __init__(self, value: str):
        self.value = value


class _Frame:
    def __init__(self, addr: str):
        self.local_vars = {VarName("__ws_region"): _Addr(addr)}


class _VM:
    def __init__(self, region: bytearray, addr: str = "1"):
        self._region = region
        self.data_layout = _LAYOUT
        self._addr = Address(addr)
        self.call_stack = [_Frame(addr)]

    def region_get(self, addr):
        assert isinstance(addr, Address)
        return self._region if addr == self._addr else None


class _TV:
    def __init__(self, value: object):
        self.value = value


def _account_backend() -> SqliteBackend:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER)")
    conn.commit()
    return SqliteBackend(conn)


def _make_vm(ws_id: int = 0) -> tuple[_VM, bytearray]:
    region = bytearray(_REGION_SIZE)
    region[0:4] = _zoned_encode(ws_id, 4)
    return _VM(region), region


def _session(connections, vm, initial_connector=NullDbConnector()):
    """One builtin over *connections* + a shared plan pool, bound to *vm*.
    Returns issue(sql); connection/cursor state persists across calls."""
    plans: list = []
    builtin, _reset = make_exec_sql_builtin(
        connections, plans, {}, initial_connector=initial_connector
    )

    def issue(sql: str):
        plans.append(parse_exec_sql(sql))
        return builtin([_TV(len(plans) - 1)], vm)

    return issue


def _sqlcode(region: bytearray) -> int:
    return _zoned_decode(bytes(region[4:13]))


def _count(backend: SqliteBackend, acct_id: int) -> int:
    cur = backend._conn.execute(
        "SELECT COUNT(*) FROM ACCOUNT WHERE ACCT_ID = ?", [acct_id]
    )
    return cur.fetchone()[0]


def test_data_statement_before_connect_is_minus_1024():
    """A run starts disconnected: INSERT before CONNECT → -1024, no row lands."""
    backend = _account_backend()
    vm, region = _make_vm(ws_id=7)
    issue = _session({"SAMPLE": backend}, vm)
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")
    assert _sqlcode(region) == -1024
    assert _count(backend, 7) == 0


def test_connect_then_insert_lands_row():
    backend = _account_backend()
    vm, region = _make_vm(ws_id=7)
    issue = _session({"SAMPLE": backend}, vm)
    assert issue("EXEC SQL CONNECT TO SAMPLE END-EXEC") is not None
    assert _sqlcode(region) == 0
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")
    assert _sqlcode(region) == 0
    assert _count(backend, 7) == 1


def test_reconnect_to_current_db_is_idempotent():
    """The testbed's unconditional double-CONNECT idiom: re-CONNECT to the same
    db (with ignored credentials) succeeds with SQLCODE 0 both times."""
    backend = _account_backend()
    vm, region = _make_vm(ws_id=1)
    issue = _session({"SAMPLE": backend}, vm)
    issue("EXEC SQL CONNECT TO sample END-EXEC")
    assert _sqlcode(region) == 0
    issue("EXEC SQL CONNECT TO sample USER :WS-ID USING :WS-ID END-EXEC")
    assert _sqlcode(region) == 0
    # Still connected: a data statement works.
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")
    assert _sqlcode(region) == 0


def test_connect_to_unknown_db_is_minus_1013():
    backend = _account_backend()
    vm, region = _make_vm(ws_id=1)
    issue = _session({"SAMPLE": backend}, vm)
    issue("EXEC SQL CONNECT TO BOGUS END-EXEC")
    assert _sqlcode(region) == -1013
    # The failed CONNECT left the run disconnected.
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")
    assert _sqlcode(region) == -1024


def test_connect_reset_disconnects():
    backend = _account_backend()
    vm, region = _make_vm(ws_id=1)
    issue = _session({"SAMPLE": backend}, vm)
    issue("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    issue("EXEC SQL CONNECT RESET END-EXEC")
    assert _sqlcode(region) == 0
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")
    assert _sqlcode(region) == -1024


def test_connect_routes_between_registered_dbs():
    dba, dbb = _account_backend(), _account_backend()
    vm, region = _make_vm(ws_id=0)
    issue = _session({"DBA": dba, "DBB": dbb}, vm)

    region[0:4] = _zoned_encode(111, 4)
    issue("EXEC SQL CONNECT TO DBA END-EXEC")
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")

    region[0:4] = _zoned_encode(222, 4)
    issue("EXEC SQL CONNECT TO DBB END-EXEC")
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")

    assert _count(dba, 111) == 1 and _count(dba, 222) == 0
    assert _count(dbb, 222) == 1 and _count(dbb, 111) == 0


def test_set_connection_switches_current():
    dba, dbb = _account_backend(), _account_backend()
    vm, region = _make_vm(ws_id=0)
    issue = _session({"DBA": dba, "DBB": dbb}, vm)

    issue("EXEC SQL CONNECT TO DBA END-EXEC")
    issue("EXEC SQL SET CONNECTION DBB END-EXEC")
    assert _sqlcode(region) == 0
    region[0:4] = _zoned_encode(333, 4)
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")
    assert _count(dbb, 333) == 1 and _count(dba, 333) == 0


def test_set_connection_to_unregistered_is_minus_1338():
    backend = _account_backend()
    vm, region = _make_vm(ws_id=1)
    issue = _session({"SAMPLE": backend}, vm)
    issue("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    issue("EXEC SQL SET CONNECTION OTHER END-EXEC")
    assert _sqlcode(region) == -1338


# ── initial_connector (CICS-DB2-attachment-style implicit CONNECT) ───────────
# Real CICS programs bound to a Db2 plan never issue EXEC SQL CONNECT
# themselves — the CICS Db2 attachment facility establishes the thread before
# the program's first SQL statement runs. A NamedDbConnector models that: the
# run starts already connected to a named, pre-registered backend instead of
# disconnected, with no COBOL-visible CONNECT statement required.


def test_named_db_connector_starts_already_connected():
    backend = _account_backend()
    vm, region = _make_vm(ws_id=7)
    issue = _session(
        {"SAMPLE": backend}, vm, initial_connector=NamedDbConnector("SAMPLE")
    )
    # No EXEC SQL CONNECT at all — the very first statement is a data statement.
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")
    assert _sqlcode(region) == 0
    assert _count(backend, 7) == 1


def test_null_db_connector_still_starts_disconnected():
    """Omitting initial_connector (the NullDbConnector default) preserves the
    existing faithful default."""
    backend = _account_backend()
    vm, region = _make_vm(ws_id=7)
    issue = _session({"SAMPLE": backend}, vm)
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")
    assert _sqlcode(region) == -1024
    assert _count(backend, 7) == 0


def test_named_db_connector_can_still_be_reset_and_switched():
    dba, dbb = _account_backend(), _account_backend()
    vm, region = _make_vm(ws_id=0)
    issue = _session(
        {"DBA": dba, "DBB": dbb}, vm, initial_connector=NamedDbConnector("DBA")
    )

    region[0:4] = _zoned_encode(111, 4)
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")
    assert _count(dba, 111) == 1

    issue("EXEC SQL CONNECT RESET END-EXEC")
    region[0:4] = _zoned_encode(222, 4)
    issue("EXEC SQL INSERT INTO ACCOUNT VALUES (:WS-ID) END-EXEC")
    assert _sqlcode(region) == -1024
    assert _count(dba, 222) == 0 and _count(dbb, 222) == 0
