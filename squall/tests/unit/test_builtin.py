"""
tests/unit/test_builtin.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for squall.builtins.exec_sql — the ``__exec_sql`` builtin factory.

Uses the same duck-typed _FakeVM pattern as test_binding.py.
Seed: ACCOUNT(ACCT_ID INT, ACCT_BAL INT) with one row (acct_id=1, bal=500).
Layout: WS-ID (zoned, 4), WS-BAL (zoned, 9), SQLCODE (zoned, 9).
"""

from __future__ import annotations

import sqlite3

import pytest

from squall.backends.sqlite import SqliteBackend
from squall.binding import _zoned_decode, _zoned_encode
from squall.builtins.exec_sql import make_exec_sql_builtin

# ── Layout ────────────────────────────────────────────────────────────────────

_LAYOUT = {
    "WS-ID": {
        "offset": 0,
        "length": 4,
        "category": "ZONED_DECIMAL",
        "total_digits": 4,
        "decimal_digits": 0,
        "signed": False,
    },
    "WS-BAL": {
        "offset": 4,
        "length": 9,
        "category": "ZONED_DECIMAL",
        "total_digits": 9,
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


# ── Fake VM ──────────────────────────────────────────────────────────────────
# Honour the REAL VM contract: local_vars keyed by VarName, regions by Address.
# A looser duck-type passes the unit test yet fails against the real VMState.
from interpreter.var_name import VarName
from interpreter.address import Address


class _AddrValue:
    def __init__(self, value: str):
        self.value = value


class _FakeFrame:
    def __init__(self, addr: str):
        self.local_vars = {VarName("__ws_region"): _AddrValue(addr)}


class _FakeVM:
    def __init__(self, region: bytearray, layout: dict, addr: str = "1"):
        self._region = region
        self.data_layout = layout
        self._addr = Address(addr)
        self.call_stack = [_FakeFrame(addr)]

    def region_get(self, addr):
        assert isinstance(
            addr, Address
        ), f"region_get expects Address, got {type(addr)}"
        return self._region if addr == self._addr else None


# ── TypedValue stub ───────────────────────────────────────────────────────────


class _TypedValue:
    """Minimal duck-type for a TypedValue carrying a raw Python value."""

    def __init__(self, value: object):
        self.value = value


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def backend():
    """In-memory SQLite backend seeded with ACCOUNT(1, 500)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)")
    conn.execute("INSERT INTO ACCOUNT VALUES (1, 500)")
    conn.commit()
    return SqliteBackend(conn)


def _make_vm(ws_id: int = 1) -> tuple[_FakeVM, bytearray]:
    """Return (vm, region) with WS-ID seeded to *ws_id*."""
    region = bytearray(_REGION_SIZE)
    region[0:4] = _zoned_encode(ws_id, 4)
    return _FakeVM(region, _LAYOUT), region


def _session(backend, vm):
    """A per-run session over ``{'SAMPLE': backend}`` bound to *vm*;
    ``issue(sql, *rest)`` runs one EXEC SQL with its text and any further
    call-site arguments. Connection + cursor state persist across calls."""
    builtin, *_ = make_exec_sql_builtin({"SAMPLE": backend})

    def issue(sql_text: str, *rest: str):
        return builtin([_TypedValue(sql_text), *(_TypedValue(r) for r in rest)], vm)

    return issue


def _call_builtin(backend, vm, sql_text: str):
    """Connect to SAMPLE, then run a single statement (the common case). A run
    starts disconnected, so the explicit CONNECT is required before any data
    statement reaches the backend."""
    issue = _session(backend, vm)
    issue("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    return issue(sql_text)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_select_into_hit(backend):
    """SELECT INTO with a matching row writes WS-BAL and SQLCODE=0."""
    vm, region = _make_vm(ws_id=1)
    _call_builtin(
        backend,
        vm,
        "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID END-EXEC",
    )

    bal = _zoned_decode(bytes(region[4:13]))
    sqlcode = _zoned_decode(bytes(region[13:22]))
    assert bal == 500
    assert sqlcode == 0


def test_select_into_no_row(backend):
    """SELECT INTO with no matching row → SQLCODE=100, WS-BAL unchanged."""
    vm, region = _make_vm(ws_id=999)
    _call_builtin(
        backend,
        vm,
        "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID END-EXEC",
    )

    sqlcode = _zoned_decode(bytes(region[13:22]))
    assert sqlcode == 100
    # WS-BAL should remain 0 (untouched)
    bal = _zoned_decode(bytes(region[4:13]))
    assert bal == 0


def test_insert_dml(backend):
    """INSERT statement executes, row becomes visible, SQLCODE=0."""
    vm, region = _make_vm(ws_id=2)

    # Write WS-BAL = 999 as the value to insert
    region[4:13] = _zoned_encode(999, 9)

    _call_builtin(
        backend,
        vm,
        "EXEC SQL INSERT INTO ACCOUNT (ACCT_ID, ACCT_BAL) VALUES (:WS-ID, :WS-BAL) END-EXEC",
    )

    sqlcode = _zoned_decode(bytes(region[13:22]))
    assert sqlcode == 0

    # Verify the row actually landed
    cur = backend._conn.execute("SELECT ACCT_BAL FROM ACCOUNT WHERE ACCT_ID = 2")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == 999


def test_update_zero_rows_reports_sqlcode_100(backend):
    """task-8 / forge-pkw: a real Db2 zero-row UPDATE reports SQLCODE +100 --
    the exact condition COTRTUPC:1558 branches ``WHEN SQLCODE = +100`` on to
    fall through to 9700-INSERT-RECORD.

    This drives the ACTUAL ``__exec_sql`` dispatch end-to-end (_h_query ->
    resolve_dml_sqlcode -> write_sqlcode), not a hand call to
    resolve_dml_sqlcode over a manufactured SqlResult -- see test_binding.py
    and test_backend.py for that unit-level coverage of the pure function in
    isolation. Reverting exec_sql.py's two call sites back to
    ``result.sqlcode``/``write_sqlcode(vm, code)`` (pre-task-8) makes this
    test fail with SQLCODE 0, not 100 -- verified by execution, see the
    task-8 report.
    """
    vm, region = _make_vm(ws_id=99999)  # no ACCOUNT row has this id

    _call_builtin(
        backend,
        vm,
        "EXEC SQL UPDATE ACCOUNT SET ACCT_BAL = :WS-BAL WHERE ACCT_ID = :WS-ID "
        "END-EXEC",
    )

    sqlcode = _zoned_decode(bytes(region[13:22]))
    assert sqlcode == 100


def test_fetch_on_undeclared_cursor_reports_not_open(backend):
    """FETCH against a cursor name never reached by DECLARE CURSOR is
    Db2-faithful SQLCODE -501 (cursor not open) — see
    tests/unit/test_cursor.py for the full DECLARE/OPEN/FETCH/CLOSE flow and
    the +100 end-of-cursor case, which applies only to a *declared* cursor
    with no more rows or one already CLOSEd.
    """
    vm, region = _make_vm()

    _call_builtin(
        backend,
        vm,
        "EXEC SQL FETCH C1 INTO :WS-BAL END-EXEC",
    )

    assert _zoned_decode(bytes(region[13:22])) == -501


def test_select_into_type_mismatch_fails_strict(backend):
    """A SQL text value selected into a numeric host var triggers the strict
    coercion layer: SQLCODE -301 and the host var is left untouched (atomic)."""
    vm, region = _make_vm(ws_id=1)
    before = bytes(region[4:13])  # WS-BAL bytes before the call

    _call_builtin(
        backend,
        vm,
        "EXEC SQL SELECT 'HELLO' INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID END-EXEC",
    )

    sqlcode = _zoned_decode(bytes(region[13:22]))
    assert sqlcode == -301
    assert bytes(region[4:13]) == before  # nothing written on a coercion failure


def test_returns_builtin_result(backend):
    """make_exec_sql_builtin returns a BuiltinResult with value=None on success."""
    vm, _ = _make_vm(ws_id=1)

    from interpreter.vm.vm_types import BuiltinResult

    result = _call_builtin(
        backend,
        vm,
        "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID END-EXEC",
    )
    assert isinstance(result, BuiltinResult)
    assert result.value is None


# ── No-op directives (DECLARE SECTION bookends) ───────────────────────────────
# Connection-lifecycle behaviour (CONNECT / SET CONNECTION / DISCONNECT, the
# -1024 disconnected guard, registry routing) lives in tests/unit/test_connection.py.


@pytest.mark.parametrize(
    "sql",
    [
        "EXEC SQL BEGIN DECLARE SECTION END-EXEC",
        "EXEC SQL END DECLARE SECTION END-EXEC",
    ],
)
def test_declare_section_is_noop_sqlcode_zero(backend, sql):
    """Declare-section bookends no-op with SQLCODE 0, untouched DB."""
    vm, region = _make_vm(ws_id=1)
    _call_builtin(backend, vm, sql)
    assert _zoned_decode(bytes(region[13:22])) == 0


def test_a_repeated_statement_is_parsed_once(backend):
    from squall.builtins import exec_sql

    exec_sql._parsed.cache_clear()
    vm, _region = _make_vm()
    issue = _session(backend, vm)
    text = "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID END-EXEC"
    issue("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    issue(text)
    issue(text)
    info = exec_sql._parsed.cache_info()
    assert (info.misses, info.hits) == (2, 1)


def test_an_open_without_a_declaration_reports_an_unknown_cursor(backend):
    vm, region = _make_vm()
    issue = _session(backend, vm)
    issue("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    issue("EXEC SQL OPEN NOSUCH END-EXEC")
    assert _zoned_decode(bytes(region[13:22])) == -1
