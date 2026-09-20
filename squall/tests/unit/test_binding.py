"""
tests/unit/test_binding.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for squall.binding — host-variable binding engine.

Uses a duck-typed _FakeVM (no imports from cicada or red-dragon VM internals).
"""

from __future__ import annotations

import pytest

from decimal import Decimal

from squall.binding import (
    read_params,
    write_outputs,
    write_sqlcode,
    _zoned_decode,
    _zoned_encode,
    _alpha_decode,
    _alpha_encode,
    _comp3_decode,
    _comp3_encode,
    _binary_decode,
    _binary_encode,
)

# ── Layout constants ──────────────────────────────────────────────────────────
#
#  WS-ID    9(4)  ZONED @offset=0  len=4   category=ZONED_DECIMAL
#  WS-BAL   9(9)  ZONED @offset=4  len=9   category=ZONED_DECIMAL
#  SQLCODE  S9(9) ZONED @offset=13 len=9   category=ZONED_DECIMAL
#  WS-NAME  X(10) ALPHA @offset=22 len=10  category=ALPHANUMERIC

# Full data_layout contract: real entries always carry total_digits/decimal_digits
# (the coercion layer needs them); the fakes must match or the gate sees capacity 0.
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
    "WS-NAME": {
        "offset": 22,
        "length": 10,
        "category": "ALPHANUMERIC",
        "total_digits": 10,
        "decimal_digits": 0,
        "signed": False,
    },
}

_REGION_SIZE = 32


# ── Fake VM ───────────────────────────────────────────────────────────────────


# The fake VM must honour the REAL VM contract: local_vars keyed by VarName,
# the region map keyed by Address. A looser duck-type would pass here yet fail
# against the real VMState (this is exactly the divergence the e2e would hit).
from interpreter.var_name import VarName
from interpreter.address import Address
from interpreter.cobol.cobol_constants import ByteConstants


class _FakeFrame:
    """Mimics a VM call-stack frame with the __ws_region local var (VarName-keyed)."""

    def __init__(self, addr: str):
        self.local_vars = {VarName("__ws_region"): _AddrValue(addr)}


class _AddrValue:
    def __init__(self, value: str):
        self.value = value


class _FakeVM:
    """Minimal VM honouring the real VarName/Address-keyed contract."""

    def __init__(self, region: bytearray, layout: dict, addr: str = "1"):
        self._region = region
        self.data_layout = layout
        self._addr = Address(addr)
        self.call_stack = [_FakeFrame(addr)]

    def region_get(self, addr):
        # Real region_get takes an Address; reject anything else so a regression
        # to a raw-str lookup fails loudly here instead of silently in the e2e.
        assert isinstance(
            addr, Address
        ), f"region_get expects Address, got {type(addr)}"
        return self._region if addr == self._addr else None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_vm() -> tuple[_FakeVM, bytearray]:
    """Return (vm, region) seeded with WS-ID = 11."""
    region = bytearray(_REGION_SIZE)
    # Seed WS-ID (offset 0, length 4) with the zoned encoding of 11
    region[0:4] = _zoned_encode(11, 4)
    return _FakeVM(region, _LAYOUT), region


# ── Test 1: read_params decodes ZONED_DECIMAL field ──────────────────────────


def test_read_params_zoned_field():
    vm, _ = _make_vm()
    result = read_params(vm, ("WS-ID",), {})
    assert result == [11]


# ── Test 2: write_outputs encodes and stores correctly ───────────────────────


def test_write_outputs_zoned_field():
    vm, region = _make_vm()
    write_outputs(vm, ("WS-BAL",), (500,), {})
    # Verify by decoding the bytes directly
    raw = bytes(region[4:13])
    assert _zoned_decode(raw) == 500


# ── Test 3: write_sqlcode positive ───────────────────────────────────────────


def test_write_sqlcode_positive():
    vm, region = _make_vm()
    write_sqlcode(vm, 100)
    raw = bytes(region[13:22])
    assert _zoned_decode(raw) == 100


# ── Test 4: write_sqlcode negative round-trips ───────────────────────────────


def test_write_sqlcode_negative():
    vm, region = _make_vm()
    write_sqlcode(vm, -1)
    raw = bytes(region[13:22])
    assert _zoned_decode(raw) == -1


# ── Test 5: ALPHANUMERIC field round-trips a string ──────────────────────────


def test_write_read_alpha_field():
    vm, region = _make_vm()
    # Write a string into WS-NAME via write_outputs
    write_outputs(vm, ("WS-NAME",), ("ALICE",), {})
    # Read it back via read_params
    result = read_params(vm, ("WS-NAME",), {})
    assert result == ["ALICE"]


# ── Test 6: codec helper round-trips ─────────────────────────────────────────


@pytest.mark.parametrize(
    "n,length",
    [
        (0, 4),
        (1, 4),
        (11, 4),
        (9999, 4),
        (500, 9),
        (123456789, 9),
        (-1, 9),
        (-500, 9),
        (-123456789, 9),
    ],
)
def test_zoned_encode_decode_roundtrip(n, length):
    encoded = _zoned_encode(n, length)
    assert len(encoded) == length
    assert _zoned_decode(encoded) == n


@pytest.mark.parametrize(
    "s,length",
    [
        ("ALICE", 10),
        ("", 10),
        ("HELLO WORLD", 11),
        ("X", 1),
    ],
)
def test_alpha_encode_decode_roundtrip(s, length):
    encoded = _alpha_encode(s, length)
    assert len(encoded) == length
    decoded = _alpha_decode(encoded)
    assert decoded == s.strip()


# ── Test 7: read_params with multiple fields ──────────────────────────────────


def test_read_params_multiple_fields():
    vm, region = _make_vm()
    write_outputs(vm, ("WS-BAL",), (42,), {})
    result = read_params(vm, ("WS-ID", "WS-BAL"), {})
    assert result == [11, 42]


# ── Test 8: missing field returns None ───────────────────────────────────────


def test_read_params_missing_field_fails_loudly():
    """A host var absent from data_layout is an invariant violation, not a
    silently-tolerated None — read_params raises rather than fabricating a value."""
    vm, _ = _make_vm()
    with pytest.raises(KeyError):
        read_params(vm, ("NO-SUCH-FIELD",), {})


# ── Test 9: COMP-3 (packed decimal) field decodes to Decimal ─────────────────
#
# Layout uses the REAL data_layout entry shape (as confirmed empirically):
#   ACCT-BAL PIC S9(7)V9(2) COMP-3:
#   {"offset": 0, "length": 5, "category": "COMP3",
#    "total_digits": 9, "decimal_digits": 2, "signed": True}

_COMP3_LAYOUT = {
    "ACCT-BAL": {
        "offset": 0,
        "length": 5,
        "category": "COMP3",
        "total_digits": 9,
        "decimal_digits": 2,
        "signed": True,
    },
}

_COMP3_REGION_SIZE = 8


def _make_comp3_vm(value: Decimal) -> tuple[_FakeVM, bytearray]:
    """Return (vm, region) with ACCT-BAL pre-encoded."""
    region = bytearray(_COMP3_REGION_SIZE)
    encoded = _comp3_encode(value, 9, 2, signed=True)
    region[0:5] = encoded
    return _FakeVM(region, _COMP3_LAYOUT), region


def test_read_params_comp3_field():
    """read_params returns Decimal for a COMP3 field."""
    vm, _ = _make_comp3_vm(Decimal("1234.56"))
    result = read_params(vm, ("ACCT-BAL",), {})
    assert result == [Decimal("1234.56")]


def test_write_outputs_comp3_field():
    """write_outputs stores a Decimal correctly in a COMP3 field."""
    region = bytearray(_COMP3_REGION_SIZE)
    vm = _FakeVM(region, _COMP3_LAYOUT)
    write_outputs(vm, ("ACCT-BAL",), (Decimal("9876.54"),), {})
    raw = bytes(region[0:5])
    assert _comp3_decode(raw, decimal_digits=2) == Decimal("9876.54")


def test_read_write_comp3_roundtrip():
    """Round-trip: write Decimal to COMP3 field, read it back via read_params."""
    region = bytearray(_COMP3_REGION_SIZE)
    vm = _FakeVM(region, _COMP3_LAYOUT)
    write_outputs(vm, ("ACCT-BAL",), (Decimal("-0.01"),), {})
    result = read_params(vm, ("ACCT-BAL",), {})
    assert result == [Decimal("-0.01")]


# ── Test 10: BINARY field and write_sqlcode with BINARY SQLCODE ──────────────
#
# SQLCODE PIC S9(9) COMP (real SQLCA shape):
#   {"offset": 0, "length": 4, "category": "BINARY",
#    "total_digits": 9, "decimal_digits": 0, "signed": True}
# ACCT-ID PIC S9(9) COMP:
#   {"offset": 4, "length": 4, "category": "BINARY",
#    "total_digits": 9, "decimal_digits": 0, "signed": True}

_BINARY_LAYOUT = {
    "SQLCODE": {
        "offset": 0,
        "length": 4,
        "category": "BINARY",
        "total_digits": 9,
        "decimal_digits": 0,
        "signed": True,
    },
    "ACCT-ID": {
        "offset": 4,
        "length": 4,
        "category": "BINARY",
        "total_digits": 9,
        "decimal_digits": 0,
        "signed": True,
    },
}

_BINARY_REGION_SIZE = 8


def _make_binary_vm() -> tuple[_FakeVM, bytearray]:
    region = bytearray(_BINARY_REGION_SIZE)
    return _FakeVM(region, _BINARY_LAYOUT), region


def test_read_params_binary_field():
    """read_params returns int for a BINARY field."""
    region = bytearray(_BINARY_REGION_SIZE)
    # Encode ACCT-ID = 42 at offset 4
    region[4:8] = _binary_encode(42, 4, signed=True)
    vm = _FakeVM(region, _BINARY_LAYOUT)
    result = read_params(vm, ("ACCT-ID",), {})
    assert result == [42]


def test_write_outputs_binary_field():
    """write_outputs stores an int correctly in a BINARY field."""
    vm, region = _make_binary_vm()
    write_outputs(vm, ("ACCT-ID",), (1234567,), {})
    raw = bytes(region[4:8])
    assert _binary_decode(raw, signed=True) == 1234567


def test_write_sqlcode_binary_zero():
    """write_sqlcode(0) with a BINARY SQLCODE field encodes as zero."""
    vm, region = _make_binary_vm()
    write_sqlcode(vm, 0)
    raw = bytes(region[0:4])
    assert _binary_decode(raw, signed=True) == 0


def test_write_sqlcode_binary_negative():
    """write_sqlcode(-1) with a BINARY SQLCODE field encodes as -1."""
    vm, region = _make_binary_vm()
    write_sqlcode(vm, -1)
    raw = bytes(region[0:4])
    assert _binary_decode(raw, signed=True) == -1


def test_write_sqlcode_binary_positive():
    """write_sqlcode(100) with a BINARY SQLCODE field encodes as 100."""
    vm, region = _make_binary_vm()
    write_sqlcode(vm, 100)
    raw = bytes(region[0:4])
    assert _binary_decode(raw, signed=True) == 100


def test_write_sqlcode_still_works_for_zoned():
    """write_sqlcode with ZONED_DECIMAL SQLCODE (old shape) still works."""
    # The original SQLCODE in test_binding.py uses ZONED_DECIMAL
    vm, region = _make_vm()
    write_sqlcode(vm, -1)
    raw = bytes(region[13:22])
    assert _zoned_decode(raw) == -1


# ── Test 11: write_sqlcode populates SQLERRM (task-8) ────────────────────────
#
# Real SQLCA shape for SQLERRM (see squall/copybooks/SQLCA.cpy):
#   05  SQLERRM.
#       49  SQLERRML   PIC S9(4) COMP.   (2-byte signed binary length)
#       49  SQLERRMC   PIC X(70).        (message text)

_SQLCA_LAYOUT = {
    "SQLCODE": {
        "offset": 0,
        "length": 4,
        "category": "BINARY",
        "total_digits": 9,
        "decimal_digits": 0,
        "signed": True,
    },
    "SQLERRML": {
        "offset": 4,
        "length": 2,
        "category": "BINARY",
        "total_digits": 4,
        "decimal_digits": 0,
        "signed": True,
    },
    "SQLERRMC": {
        "offset": 6,
        "length": 70,
        "category": "ALPHANUMERIC",
        "total_digits": 70,
        "decimal_digits": 0,
        "signed": False,
    },
}
_SQLCA_REGION_SIZE = 76


def _make_sqlca_vm() -> tuple[_FakeVM, bytearray]:
    region = bytearray(_SQLCA_REGION_SIZE)
    return _FakeVM(region, _SQLCA_LAYOUT), region


def test_write_sqlcode_populates_sqlerrm():
    """A non-empty message writes SQLERRML (its length) and SQLERRMC (the
    text, space-padded) -- the driver's own prose, deliberately, not Db2's
    token-substitution format (see resolve_dml_sqlcode/write_sqlcode
    docstrings for the ruling)."""
    vm, region = _make_sqlca_vm()
    write_sqlcode(vm, -204, "TABLE not found")

    assert _binary_decode(bytes(region[4:6]), signed=True) == len("TABLE not found")
    assert _alpha_decode(bytes(region[6:76])) == "TABLE not found"
    assert _binary_decode(bytes(region[0:4]), signed=True) == -204


def test_write_sqlcode_truncates_long_message_to_70_bytes():
    """A message longer than SQLERRMC's PIC X(70) is truncated, never raises."""
    vm, region = _make_sqlca_vm()
    long_message = "x" * 100
    write_sqlcode(vm, -204, long_message)

    assert _binary_decode(bytes(region[4:6]), signed=True) == 70
    assert _alpha_decode(bytes(region[6:76])) == "x" * 70


def test_write_sqlcode_empty_message_clears_stale_sqlerrm():
    """task-8 review round 1: real Db2 resets SQLCA on every statement. A
    prior statement's error text (e.g. -911 'deadlock...') must not survive
    into a later statement that fails with no driver text (or succeeds) --
    an empty message BLANKS SQLERRM (LEN 0, TEXT all spaces), it does not
    leave the previous statement's prose in place for COTRTUPC to STRING
    into the operator's screen."""
    vm, region = _make_sqlca_vm()
    write_sqlcode(vm, -911, "deadlock detected")
    assert _binary_decode(bytes(region[4:6]), signed=True) == len("deadlock detected")

    write_sqlcode(vm, 0, "")

    assert _binary_decode(bytes(region[4:6]), signed=True) == 0
    assert bytes(region[6:76]) == bytes([ByteConstants.EBCDIC_SPACE]) * 70


def test_write_sqlcode_message_is_a_noop_without_sqlca_fields():
    """Most binding-test fixtures (and every earlier write_sqlcode caller)
    lay out only SQLCODE, with no SQLERRML/SQLERRMC at all. Passing a
    message must stay a silent no-op there, not raise KeyError -- backward
    compatibility for every pre-task-8 write_sqlcode(vm, code) call site."""
    vm, region = _make_vm()
    write_sqlcode(vm, -1, "some driver error text")
    raw = bytes(region[13:22])
    assert _zoned_decode(raw) == -1  # SQLCODE still written correctly


# ── Test 12: resolve_dml_sqlcode -- kind-keyed +100 zero-row mapping (task-8,
# forge-pkw) ───────────────────────────────────────────────────────────────
#
# Live-verified against Db2 (see tests/unit/test_backend.py): a zero-row
# UPDATE/DELETE/INSERT returns rowcount=0, sqlcode=0 from the backend --
# Db2's own +100 convention is applied here, in the binding layer, keyed by
# statement Kind so DDL (CREATE, lowered as Kind.GENERIC, which legitimately
# reports rowcount=-1) is never mistaken for a zero-row DML statement.


def test_resolve_dml_sqlcode_update_zero_rows_is_100():
    from squall.backend import SqlResult
    from squall.parser.sql_model import Kind
    from squall.binding import resolve_dml_sqlcode

    result = SqlResult(rows=(), rowcount=0, sqlcode=0)
    assert resolve_dml_sqlcode(Kind.UPDATE, result) == 100


def test_resolve_dml_sqlcode_insert_zero_rows_is_100():
    from squall.backend import SqlResult
    from squall.parser.sql_model import Kind
    from squall.binding import resolve_dml_sqlcode

    result = SqlResult(rows=(), rowcount=0, sqlcode=0)
    assert resolve_dml_sqlcode(Kind.INSERT, result) == 100


def test_resolve_dml_sqlcode_delete_zero_rows_is_100():
    from squall.backend import SqlResult
    from squall.parser.sql_model import Kind
    from squall.binding import resolve_dml_sqlcode

    result = SqlResult(rows=(), rowcount=0, sqlcode=0)
    assert resolve_dml_sqlcode(Kind.DELETE, result) == 100


def test_resolve_dml_sqlcode_update_affecting_rows_stays_zero():
    from squall.backend import SqlResult
    from squall.parser.sql_model import Kind
    from squall.binding import resolve_dml_sqlcode

    result = SqlResult(rows=(), rowcount=3, sqlcode=0)
    assert resolve_dml_sqlcode(Kind.UPDATE, result) == 0


def test_resolve_dml_sqlcode_merge_zero_rows_is_100():
    """task-8 review round 1: real Db2 applies the same +100 zero-row
    convention to MERGE, not only INSERT/UPDATE/DELETE."""
    from squall.backend import SqlResult
    from squall.parser.sql_model import Kind
    from squall.binding import resolve_dml_sqlcode

    result = SqlResult(rows=(), rowcount=0, sqlcode=0)
    assert resolve_dml_sqlcode(Kind.MERGE, result) == 100


def test_resolve_dml_sqlcode_execute_zero_rows_is_100():
    """task-8 review round 1: EXECUTE runs a previously-PREPAREd dynamic
    statement whose underlying operation is an INSERT/UPDATE/DELETE/MERGE
    (a plain dynamic SELECT has no EXECUTE form -- it needs a cursor or
    EXECUTE...INTO, which never reaches this sqlcode==0/rowcount==0 guard
    because the backend's result-set branch already sets sqlcode 100 for
    zero rows). Same +100 convention applies."""
    from squall.backend import SqlResult
    from squall.parser.sql_model import Kind
    from squall.binding import resolve_dml_sqlcode

    result = SqlResult(rows=(), rowcount=0, sqlcode=0)
    assert resolve_dml_sqlcode(Kind.EXECUTE, result) == 100


def test_resolve_dml_sqlcode_generic_ddl_rowcount_minus_one_not_caught():
    """CREATE TABLE lowers to Kind.GENERIC and legitimately reports
    rowcount=-1 (Db2-verified) -- the zero-row mapping must not fire for it,
    or every CREATE would wrongly become SQLCODE +100."""
    from squall.backend import SqlResult
    from squall.parser.sql_model import Kind
    from squall.binding import resolve_dml_sqlcode

    result = SqlResult(rows=(), rowcount=-1, sqlcode=0)
    assert resolve_dml_sqlcode(Kind.GENERIC, result) == 0


def test_resolve_dml_sqlcode_negative_sqlcode_passes_through_unchanged():
    """A genuine driver error on an UPDATE/DELETE/INSERT is untouched -- the
    +100 mapping only ever applies to a clean rowcount=0/sqlcode=0 result."""
    from squall.backend import SqlResult
    from squall.parser.sql_model import Kind
    from squall.binding import resolve_dml_sqlcode

    result = SqlResult(rows=(), rowcount=0, sqlcode=-911)
    assert resolve_dml_sqlcode(Kind.UPDATE, result) == -911


def test_resolve_dml_sqlcode_select_into_kind_untouched():
    """SELECT_INTO is bound separately (_bind_row in exec_sql.py) and never
    reaches resolve_dml_sqlcode in practice, but the function itself must
    not apply the DML zero-row rule to it either."""
    from squall.backend import SqlResult
    from squall.parser.sql_model import Kind
    from squall.binding import resolve_dml_sqlcode

    result = SqlResult(rows=(), rowcount=0, sqlcode=0)
    assert resolve_dml_sqlcode(Kind.SELECT_INTO, result) == 0
