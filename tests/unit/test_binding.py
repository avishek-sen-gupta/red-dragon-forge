"""
tests/unit/test_binding.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for squall.binding — host-variable binding engine.

Uses a duck-typed _FakeVM (no imports from cicada or red-dragon VM internals).
"""

from __future__ import annotations

import pytest

from squall.binding import (
    read_params,
    write_outputs,
    write_sqlcode,
    _zoned_decode,
    _zoned_encode,
    _alpha_decode,
    _alpha_encode,
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


class _FakeFrame:
    """Mimics a VM call-stack frame with a single local var."""

    def __init__(self, addr: str):
        # key must support .name or str() => "__ws_region"
        self.local_vars = {_VarKey("__ws_region"): _AddrValue(addr)}


class _VarKey:
    def __init__(self, name: str):
        self.name = name

    def __str__(self):
        return self.name


class _AddrValue:
    def __init__(self, value: str):
        self.value = value


class _FakeVM:
    """Minimal duck-typed VM for binding tests."""

    def __init__(self, region: bytearray, layout: dict, addr: str = "1"):
        self._region = region
        self.data_layout = layout
        self._addr = addr
        self.call_stack = [_FakeFrame(addr)]

    def region_get(self, addr):
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
