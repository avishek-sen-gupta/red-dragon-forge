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
from squall.dclgen_meta import derive_field_meta

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


def test_varchar_trailing_space_is_preserved():
    """task-8: LEN already delimits the value exactly, so a value that
    genuinely ends in a space must round-trip WITH that space. Pre-fix,
    ``_varchar_decode`` routed through ``_alpha_decode`` (which rstrips for
    the *fixed-width, pad-with-spaces* ALPHANUMERIC case) and silently lost
    it -- 'SANDERS ' (8 chars, LEN=8) would read back as 'SANDERS' (7 chars).
    """
    region = bytearray(_REGION_SIZE)
    vm = _VM(region)

    status = write_outputs(vm, ("EMP-NAME",), ("SANDERS ",), field_meta=_FIELD_META)
    assert status == 0

    # LEN child holds 8 (the space counts), not 7.
    assert int.from_bytes(bytes(region[2:4]), "big", signed=True) == 8

    vals = read_params(vm, ("EMP-NAME",), field_meta=_FIELD_META)
    assert vals == ["SANDERS "]


# ── DCLGEN VARCHAR round-trip -- forge-yuo (field_meta derived, no sidecar) ───
#
# The real defect: CardDemo's hand-written DCLTRTYP.dcl carries no
# squall-generated <NAME>.json sidecar, so field_meta was {} and every
# VARCHAR host var fell through to the flat byte codec. Reading
# :DCL-TR-DESCRIPTION returned '\x00\x97PURCHASE' (the binary length prefix
# misread as text); writing 'CASH ADVANCE' set LEN = -15423 and
# TEXT = 'SH ADVANCE'. field_meta here comes ONLY from derive_field_meta
# (squall.dclgen_meta) over the raw bridge JSON -- no sidecar at all -- to
# prove the shape-recognition path, not just the (already-tested) codec.

# Real bridge JSON for `10 DCL-TR-DESCRIPTION.` under DCLTRANSACTION-TYPE in
# vendor/carddemo's DCLTRTYP.dcl (dumped from an actual compile_program run;
# see squall/tests/unit/test_dclgen_meta.py's module docstring).
_DCLTRTYP_BRIDGE_GROUP = {
    "name": "DCL-TR-DESCRIPTION",
    "level": 10,
    "pic": "",
    "usage": "DISPLAY",
    "children": [
        {
            "name": "DCL-TR-DESCRIPTION-LEN",
            "level": 49,
            "pic": "S9(4)",
            "usage": "COMP",
        },
        {
            "name": "DCL-TR-DESCRIPTION-TEXT",
            "level": 49,
            "pic": "X(50)",
            "usage": "DISPLAY",
        },
    ],
}

# ProLeap's real layout for DCLTRTYP's 01 DCLTRANSACTION-TYPE record:
#   DCL-TR-TYPE               ALPHANUMERIC @0 len 2   (PIC X(2))
#   DCL-TR-DESCRIPTION        ALPHANUMERIC @2 len 52  (the 49-group itself,
#                                                       spanning its two children)
#   DCL-TR-DESCRIPTION-LEN    BINARY       @2 len 2   (signed S9(4) COMP)
#   DCL-TR-DESCRIPTION-TEXT   ALPHANUMERIC @4 len 50  (PIC X(50))
#
# The group entry matters here: pre-fix, field_meta has no "DCL-TR-DESCRIPTION"
# entry at all, so _plan_assignment/_read_one fall through to the FLAT-field
# path and look up "DCL-TR-DESCRIPTION" itself (not its LEN/TEXT children) in
# data_layout. Omitting it would make a pre-fix revert raise KeyError instead
# of reproducing the measured corruption (LEN = -15423, TEXT = 'SH ADVANCE') —
# a characterisation test that fails on the wrong exception instead of the
# behaviour it documents.
_DCLTRTYP_LAYOUT = {
    "DCL-TR-TYPE": {
        "offset": 0,
        "length": 2,
        "category": "ALPHANUMERIC",
        "total_digits": 2,
        "decimal_digits": 0,
        "signed": False,
    },
    "DCL-TR-DESCRIPTION": {
        "offset": 2,
        "length": 52,
        "category": "ALPHANUMERIC",
        "total_digits": 52,
        "decimal_digits": 0,
        "signed": False,
    },
    "DCL-TR-DESCRIPTION-LEN": {
        "offset": 2,
        "length": 2,
        "category": "BINARY",
        "total_digits": 4,
        "decimal_digits": 0,
        "signed": True,
    },
    "DCL-TR-DESCRIPTION-TEXT": {
        "offset": 4,
        "length": 50,
        "category": "ALPHANUMERIC",
        "total_digits": 50,
        "decimal_digits": 0,
        "signed": False,
    },
}
_DCLTRTYP_REGION_SIZE = 54


def test_varchar_host_variable_round_trips_exactly_with_derived_field_meta():
    """With ``field_meta={}`` (pre-fix: no sidecar, no derivation), writing
    'CASH ADVANCE' falls through to the flat ALPHANUMERIC path over the whole
    52-byte group and measurably reproduces the real defect: LEN decodes as
    -15423 (the first two EBCDIC bytes of "CASH ADVANCE", 'C'=0xC3/'A'=0xC1,
    misread as a signed big-endian binary) -- verified directly against
    ``_DCLTRTYP_LAYOUT`` before writing this test. This is why
    ``_DCLTRTYP_LAYOUT`` below carries the "DCL-TR-DESCRIPTION" *group* entry
    in addition to its LEN/TEXT children: without it, a pre-fix revert would
    raise KeyError (the flat path's ``_require_field(data_layout, name)``
    lookup on the group name) instead of reproducing this corruption -- a
    characterisation test that fails on the wrong exception instead of the
    behaviour it documents.

    Assert on the stored bytes too, not just the round-tripped value -- a
    write and a read that are wrong in compensating ways would otherwise
    still "round trip"."""
    field_meta = derive_field_meta({"data_fields": [_DCLTRTYP_BRIDGE_GROUP]})
    region = bytearray(_DCLTRTYP_REGION_SIZE)
    vm = _VM(region)
    vm.data_layout = _DCLTRTYP_LAYOUT

    status = write_outputs(
        vm, ("DCL-TR-DESCRIPTION",), ("CASH ADVANCE",), field_meta=field_meta
    )
    assert status == 0

    # LEN child holds 12 as a 2-byte big-endian binary.
    assert int.from_bytes(bytes(region[2:4]), "big", signed=True) == 12
    # TEXT child starts with 'CASH ADVANCE' (EBCDIC), padded to its full length.
    assert _alpha_decode(bytes(region[4:16])) == "CASH ADVANCE"

    assert read_params(vm, ("DCL-TR-DESCRIPTION",), field_meta=field_meta) == [
        "CASH ADVANCE"
    ]


class _Arg:
    def __init__(self, value):
        self.value = value


def test_a_fetch_into_a_varchar_binds_through_the_shape_its_call_carries():
    import sqlite3

    from squall.backends.sqlite import SqliteBackend
    from squall.builtins.exec_sql import make_exec_sql_builtin

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE EMP (EMP_NAME VARCHAR(9))")
    conn.execute("INSERT INTO EMP VALUES ('SANDERS')")
    region = bytearray(_REGION_SIZE + 9)
    vm = _VM(region)
    vm.data_layout = {
        **_LAYOUT,
        "SQLCODE": {
            "offset": _REGION_SIZE,
            "length": 9,
            "category": "ZONED_DECIMAL",
            "total_digits": 9,
            "decimal_digits": 0,
            "signed": True,
        },
    }
    builtin, *_ = make_exec_sql_builtin({"SAMPLE": SqliteBackend(conn)})
    declare = "EXEC SQL DECLARE C1 CURSOR FOR SELECT EMP_NAME FROM EMP END-EXEC"
    calls = (
        ("EXEC SQL CONNECT TO SAMPLE END-EXEC",),
        ("EXEC SQL OPEN C1 END-EXEC", declare),
        (
            "EXEC SQL FETCH C1 INTO :EMP-NAME END-EXEC",
            "EMP-NAME",
            "EMP-NAME-LEN",
            "EMP-NAME-TEXT",
        ),
    )
    for call in calls:
        builtin([_Arg(value) for value in call], vm)

    assert (
        int.from_bytes(bytes(region[2:4]), "big", signed=True),
        _alpha_decode(bytes(region[4:11])),
    ) == (7, "SANDERS")
