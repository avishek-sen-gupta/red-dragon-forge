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
    "WS-ID": {"offset": 0, "length": 4, "category": "ZONED_DECIMAL"},
    "WS-BAL": {"offset": 4, "length": 9, "category": "ZONED_DECIMAL"},
    "SQLCODE": {"offset": 13, "length": 9, "category": "ZONED_DECIMAL"},
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
        assert isinstance(addr, Address), f"region_get expects Address, got {type(addr)}"
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


def _call_builtin(builtin, vm, sql_text: str) -> None:
    """Call *builtin* with a single _TypedValue arg wrapping *sql_text*."""
    builtin([_TypedValue(sql_text)], vm)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_select_into_hit(backend):
    """SELECT INTO with a matching row writes WS-BAL and SQLCODE=0."""
    vm, region = _make_vm(ws_id=1)
    builtin = make_exec_sql_builtin(backend)

    _call_builtin(
        builtin,
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
    builtin = make_exec_sql_builtin(backend)

    _call_builtin(
        builtin,
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
    builtin = make_exec_sql_builtin(backend)

    # Write WS-BAL = 999 as the value to insert
    region[4:13] = _zoned_encode(999, 9)

    _call_builtin(
        builtin,
        vm,
        "EXEC SQL INSERT INTO ACCOUNT (ACCT_ID, ACCT_BAL) VALUES (:WS-ID, :WS-BAL) END-EXEC",
    )

    sqlcode = _zoned_decode(bytes(region[13:22]))
    assert sqlcode == 0

    # Verify the row actually landed
    cur = backend._conn.execute(
        "SELECT ACCT_BAL FROM ACCOUNT WHERE ACCT_ID = 2"
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == 999


def test_fetch_raises_not_implemented(backend):
    """FETCH cursor kind raises NotImplementedError (slice-1 not supported)."""
    vm, _ = _make_vm()
    builtin = make_exec_sql_builtin(backend)

    with pytest.raises(NotImplementedError, match="squall slice 1: fetch not yet supported"):
        _call_builtin(
            builtin,
            vm,
            "EXEC SQL FETCH C1 INTO :WS-BAL END-EXEC",
        )


def test_returns_builtin_result(backend):
    """make_exec_sql_builtin returns a BuiltinResult with value=None on success."""
    vm, _ = _make_vm(ws_id=1)
    builtin = make_exec_sql_builtin(backend)

    from interpreter.vm.vm_types import BuiltinResult

    result = builtin(
        [_TypedValue(
            "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID END-EXEC"
        )],
        vm,
    )
    assert isinstance(result, BuiltinResult)
    assert result.value is None
