"""
tests/unit/test_varchar.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The VARCHAR 49-group codec at the binding layer.

A VARCHAR host var is an IBM DCLGEN group: ``<HV>`` (the group) over two 49-level
children — ``<HV>-LEN`` (binary length prefix) and ``<HV>-TEXT`` (the chars). The
flat data_layout records all three but cannot mark the group as VARCHAR; the
dclgen ``field_meta`` map supplies that, naming the LEN/TEXT children. read/write
then drive the length-prefixed codec over those children.
"""

from __future__ import annotations

from squall.binding import read_params, write_outputs, _alpha_decode

from interpreter.var_name import VarName
from interpreter.address import Address

# Mirrors ProLeap's real layout for a 49-group (verified against the bridge):
#   EMP-NAME (group)     ALPHANUMERIC @2 len 11
#   EMP-NAME-LEN         BINARY       @2 len 2  (signed S9(4) COMP)
#   EMP-NAME-TEXT        ALPHANUMERIC @4 len 9
_LAYOUT = {
    "EMP-NAME": {
        "offset": 2,
        "length": 11,
        "category": "ALPHANUMERIC",
        "total_digits": 11,
        "decimal_digits": 0,
        "signed": False,
    },
    "EMP-NAME-LEN": {
        "offset": 2,
        "length": 2,
        "category": "BINARY",
        "total_digits": 4,
        "decimal_digits": 0,
        "signed": True,
    },
    "EMP-NAME-TEXT": {
        "offset": 4,
        "length": 9,
        "category": "ALPHANUMERIC",
        "total_digits": 9,
        "decimal_digits": 0,
        "signed": False,
    },
}
_REGION_SIZE = 13

_FIELD_META = {
    "EMP-NAME": {
        "host_var": "EMP-NAME",
        "category": "VARCHAR",
        "sql_type": "VARCHAR(9)",
        "length": 9,
        "len_var": "EMP-NAME-LEN",
        "text_var": "EMP-NAME-TEXT",
    }
}


class _AddrValue:
    def __init__(self, v):
        self.value = v


class _Frame:
    def __init__(self, addr):
        self.local_vars = {VarName("__ws_region"): _AddrValue(addr)}


class _VM:
    def __init__(self, region, addr="1"):
        self._region = region
        self.data_layout = _LAYOUT
        self._addr = Address(addr)
        self.call_stack = [_Frame(addr)]

    def region_get(self, addr):
        assert isinstance(addr, Address)
        return self._region if addr == self._addr else None


def test_varchar_write_then_read_round_trips():
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)

    status = write_outputs(vm, ("EMP-NAME",), ("SANDERS",), field_meta=_FIELD_META)
    assert status == 0

    # LEN child holds 7 as a 2-byte big-endian binary (squall's COMP convention).
    assert int.from_bytes(bytes(region[2:4]), "big", signed=True) == 7
    # TEXT child holds 'SANDERS' (EBCDIC) in its first 7 bytes.
    assert _alpha_decode(bytes(region[4:11])) == "SANDERS"

    # Reading back yields exactly the LEN-many characters (no padding).
    vals = read_params(vm, ("EMP-NAME",), field_meta=_FIELD_META)
    assert vals == ["SANDERS"]


def test_varchar_overflow_fails_atomically():
    """A value longer than the declared VARCHAR length fails (-304), writes nothing."""
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)
    before = bytes(region)

    status = write_outputs(vm, ("EMP-NAME",), ("TOOLONGNAME",), field_meta=_FIELD_META)
    assert status == -304
    assert bytes(region) == before  # atomic: nothing written on overflow


def test_varchar_empty_string():
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)

    assert write_outputs(vm, ("EMP-NAME",), ("",), field_meta=_FIELD_META) == 0
    assert int.from_bytes(bytes(region[2:4]), "big", signed=True) == 0
    assert read_params(vm, ("EMP-NAME",), field_meta=_FIELD_META) == [""]
