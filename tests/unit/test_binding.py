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

_LAYOUT = {
    "WS-ID": {"offset": 0, "length": 4, "category": "ZONED_DECIMAL"},
    "WS-BAL": {"offset": 4, "length": 9, "category": "ZONED_DECIMAL"},
    "SQLCODE": {"offset": 13, "length": 9, "category": "ZONED_DECIMAL"},
    "WS-NAME": {"offset": 22, "length": 10, "category": "ALPHANUMERIC"},
}

_REGION_SIZE = 32


# ── Fake VM ───────────────────────────────────────────────────────────────────


# The fake VM must honour the REAL VM contract: local_vars keyed by VarName,
# the region map keyed by Address. A looser duck-type would pass here yet fail
# against the real VMState (this is exactly the divergence the e2e would hit).
from interpreter.var_name import VarName
from interpreter.address import Address


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
        assert isinstance(addr, Address), f"region_get expects Address, got {type(addr)}"
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
    result = read_params(vm, ("WS-ID",))
    assert result == [11]


# ── Test 2: write_outputs encodes and stores correctly ───────────────────────


def test_write_outputs_zoned_field():
    vm, region = _make_vm()
    write_outputs(vm, ("WS-BAL",), (500,))
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
    write_outputs(vm, ("WS-NAME",), ("ALICE",))
    # Read it back via read_params
    result = read_params(vm, ("WS-NAME",))
    assert result == ["ALICE"]


# ── Test 6: codec helper round-trips ─────────────────────────────────────────


@pytest.mark.parametrize("n,length", [
    (0, 4),
    (1, 4),
    (11, 4),
    (9999, 4),
    (500, 9),
    (123456789, 9),
    (-1, 9),
    (-500, 9),
    (-123456789, 9),
])
def test_zoned_encode_decode_roundtrip(n, length):
    encoded = _zoned_encode(n, length)
    assert len(encoded) == length
    assert _zoned_decode(encoded) == n


@pytest.mark.parametrize("s,length", [
    ("ALICE", 10),
    ("", 10),
    ("HELLO WORLD", 11),
    ("X", 1),
])
def test_alpha_encode_decode_roundtrip(s, length):
    encoded = _alpha_encode(s, length)
    assert len(encoded) == length
    decoded = _alpha_decode(encoded)
    assert decoded == s.strip()


# ── Test 7: read_params with multiple fields ──────────────────────────────────


def test_read_params_multiple_fields():
    vm, region = _make_vm()
    write_outputs(vm, ("WS-BAL",), (42,))
    result = read_params(vm, ("WS-ID", "WS-BAL"))
    assert result == [11, 42]


# ── Test 8: missing field returns None ───────────────────────────────────────


def test_read_params_missing_field():
    vm, _ = _make_vm()
    result = read_params(vm, ("NO-SUCH-FIELD",))
    assert result == [None]


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
    result = read_params(vm, ("ACCT-BAL",))
    assert result == [Decimal("1234.56")]


def test_write_outputs_comp3_field():
    """write_outputs stores a Decimal correctly in a COMP3 field."""
    region = bytearray(_COMP3_REGION_SIZE)
    vm = _FakeVM(region, _COMP3_LAYOUT)
    write_outputs(vm, ("ACCT-BAL",), (Decimal("9876.54"),))
    raw = bytes(region[0:5])
    assert _comp3_decode(raw, decimal_digits=2) == Decimal("9876.54")


def test_read_write_comp3_roundtrip():
    """Round-trip: write Decimal to COMP3 field, read it back via read_params."""
    region = bytearray(_COMP3_REGION_SIZE)
    vm = _FakeVM(region, _COMP3_LAYOUT)
    write_outputs(vm, ("ACCT-BAL",), (Decimal("-0.01"),))
    result = read_params(vm, ("ACCT-BAL",))
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
    result = read_params(vm, ("ACCT-ID",))
    assert result == [42]


def test_write_outputs_binary_field():
    """write_outputs stores an int correctly in a BINARY field."""
    vm, region = _make_binary_vm()
    write_outputs(vm, ("ACCT-ID",), (1234567,))
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
