"""Unit tests for BMS screen builtins."""

import queue
import struct

from tests.covers import covers, NotLanguageFeature
from interpreter.cobol.field_position import FieldPosition
from tests.layout_build import declarations
from cics.builtins.screen import (
    make_send_map_builtin,
    make_receive_map_builtin,
    make_send_text_builtin,
)
from cics.dispatcher import InputEvent
from cics.screen.cursor import NO_CURSOR, Cursor, SymbolicCursor
from cics.screen.payload import FieldAttributes, SendMode, screen_payload
from cics.types import NO_TERMINAL, CicsContext, DispatchKind
from interpreter.types.typed_value import typed
from interpreter.types.type_expr import UNKNOWN
from interpreter.vm.vm_types import VMState, BuiltinResult

_AT_TERMINAL: list = [
    CicsContext(transid="MENU", commarea=b"", eibaid="\x7d", termid="T001")
]

_NO_TERMINAL_TASK: list = [
    CicsContext(transid="SRTD", commarea=b"", eibaid="\x7d", termid=NO_TERMINAL)
]


class _FakeVM:
    def __init__(self, region, layout, addr=1):
        self._region = region
        self.declarations = declarations(layout)
        self._addr = addr

    def region_get(self, addr):
        return self._region if addr == self._addr else None


def _tv(v):
    return typed(v, UNKNOWN)


def _send(monkeypatch, layout, region, *args):
    vm = _FakeVM(region, layout)
    monkeypatch.setattr("cics.builtins.system._get_ws_region_addr", lambda _vm: 1)
    sq: queue.Queue = queue.Queue()
    make_send_map_builtin(sq, _AT_TERMINAL)([_tv(a) for a in args], vm)
    return screen_payload(sq.get(block=False))


_LAYOUT = {
    "USERIDL": FieldPosition(
        offset=0,
        length=2,
        category="ALPHANUMERIC",
        total_digits=2,
        decimal_digits=0,
        signed=False,
    ),
    "USERIDA": FieldPosition(
        offset=2,
        length=1,
        category="ALPHANUMERIC",
        total_digits=1,
        decimal_digits=0,
        signed=False,
    ),
    "USERIDC": FieldPosition(
        offset=3,
        length=1,
        category="ALPHANUMERIC",
        total_digits=1,
        decimal_digits=0,
        signed=False,
    ),
    "USERIDH": FieldPosition(
        offset=4,
        length=1,
        category="ALPHANUMERIC",
        total_digits=1,
        decimal_digits=0,
        signed=False,
    ),
    "USERIDO": FieldPosition(
        offset=5,
        length=8,
        category="ALPHANUMERIC",
        total_digits=8,
        decimal_digits=0,
        signed=False,
    ),
}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_map_reports_mapset_and_options(monkeypatch):
    payload = _send(
        monkeypatch,
        _LAYOUT,
        bytearray(13),
        "COSGN0A",
        ["USERID"],
        "COSGN00",
        ["ERASE", "ALARM", "FREEKB"],
        "",
    )
    assert (
        payload.mapset,
        payload.mode,
        payload.erase,
        payload.alarm,
        payload.freekb,
        payload.frset,
    ) == ("COSGN00", SendMode.FULL, True, True, True, False)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bare_cursor_uses_the_field_whose_length_is_minus_one(monkeypatch):
    region = bytearray(13)
    region[0:2] = struct.pack(">h", -1)
    assert _send(
        monkeypatch, _LAYOUT, region, "M", ["USERID"], "", ["CURSOR"], ""
    ).cursor == SymbolicCursor("USERID")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cursor_value_and_no_cursor_option(monkeypatch):
    assert _send(
        monkeypatch, _LAYOUT, bytearray(13), "M", ["USERID"], "", ["CURSOR"], "245"
    ).cursor == Cursor(245)
    assert (
        _send(
            monkeypatch, _LAYOUT, bytearray(13), "M", ["USERID"], "", [], "245"
        ).cursor
        == NO_CURSOR
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_nonzero_attribute_bytes_become_overrides(monkeypatch):
    region = bytearray(13)
    region[2:5] = bytes((0xF8, 0xF2, 0x00))
    assert _send(monkeypatch, _LAYOUT, region, "M", ["USERID"]).attrs == {
        "USERID": FieldAttributes(0xF8, 0xF2, 0)
    }


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_maponly_sends_no_symbolic_data(monkeypatch):
    region = bytearray(13)
    region[5:13] = "USER0001".encode("cp037")
    payload = _send(monkeypatch, _LAYOUT, region, "M", ["USERID"], "", ["MAPONLY"], "")
    assert (payload.mode, dict(payload.fields)) == (SendMode.MAPONLY, {})


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_map_reads_named_output_fields_from_ws(monkeypatch):
    layout = {
        "USERIDO": FieldPosition(
            offset=0,
            length=8,
            category="ALPHANUMERIC",
            total_digits=8,
            decimal_digits=0,
            signed=False,
        ),
        "ERRMSGO": FieldPosition(
            offset=8,
            length=78,
            category="ALPHANUMERIC",
            total_digits=78,
            decimal_digits=0,
            signed=False,
        ),
    }
    region = bytearray(b"\x40" * 86)
    region[0:8] = "USER0001".encode("cp037")
    vm = _FakeVM(region, layout)
    monkeypatch.setattr("cics.builtins.system._get_ws_region_addr", lambda _vm: 1)
    sq: queue.Queue = queue.Queue()
    builtin = make_send_map_builtin(sq, _AT_TERMINAL)
    builtin([_tv("COSGN0A"), _tv(["USERID", "ERRMSG"])], vm)
    item = sq.get(block=False)
    assert item["map"] == "COSGN0A"
    assert item["fields"]["USERID"] == "USER0001"
    assert item["fields"]["ERRMSG"] == ""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_receive_map_writes_eibaid_from_input_event(monkeypatch):
    layout = {
        "USERIDI": FieldPosition(
            offset=0,
            length=8,
            category="ALPHANUMERIC",
            total_digits=8,
            decimal_digits=0,
            signed=False,
        ),
        "EIBAID": FieldPosition(
            offset=200,
            length=1,
            category="ALPHANUMERIC",
            total_digits=1,
            decimal_digits=0,
            signed=False,
        ),
    }
    region = bytearray(b"\x40" * 210)
    vm = _FakeVM(region, layout)
    monkeypatch.setattr("cics.builtins.system._get_ws_region_addr", lambda _vm: 1)
    vm.region_set = lambda addr, data: region.__setitem__(slice(0, len(data)), data)
    iq: queue.Queue = queue.Queue()
    iq.put(InputEvent(eibaid="\x33", fields={"USERID": "ALICE"}))
    builtin = make_receive_map_builtin(iq, _AT_TERMINAL, [None], timeout=1.0)
    builtin([_tv("COSGN0A"), _tv(["USERID"])], vm)
    # The attention key from the InputEvent lands in EIBAID in the WS region.
    assert region[200] == ord("\x33")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_receive_map_backcompat_dict_leaves_eibaid_default(monkeypatch):
    layout = {
        "USERIDI": FieldPosition(
            offset=0,
            length=8,
            category="ALPHANUMERIC",
            total_digits=8,
            decimal_digits=0,
            signed=False,
        ),
        "EIBAID": FieldPosition(
            offset=200,
            length=1,
            category="ALPHANUMERIC",
            total_digits=1,
            decimal_digits=0,
            signed=False,
        ),
    }
    region = bytearray(b"\x40" * 210)
    # Pre-seed EIBAID with a sentinel so the default write is observable.
    region[200] = 0x00
    vm = _FakeVM(region, layout)
    monkeypatch.setattr("cics.builtins.system._get_ws_region_addr", lambda _vm: 1)
    vm.region_set = lambda addr, data: region.__setitem__(slice(0, len(data)), data)
    iq: queue.Queue = queue.Queue()
    # Plain dict on the queue (legacy producers) — duck-typed as field values
    # with no .eibaid, so the default DFHENTER aid is written.
    iq.put({"USERID": "BOB"})
    builtin = make_receive_map_builtin(iq, _AT_TERMINAL, [None], timeout=1.0)
    builtin([_tv("COSGN0A"), _tv(["USERID"])], vm)
    # A named input field still writes into the WS region.
    assert region[0:8].decode("cp037").rstrip() == "BOB"
    # Default EIBAID (DFHENTER) is written when the item has no .eibaid.
    assert region[200] == 0x7D


class _InputEvent:
    def __init__(self, fields, eibaid="\x7d"):
        self.fields = fields
        self.eibaid = eibaid


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_receive_map_writes_named_input_fields_to_ws(monkeypatch):
    import struct

    layout = {
        "USERIDI": FieldPosition(
            offset=0,
            length=8,
            category="ALPHANUMERIC",
            total_digits=8,
            decimal_digits=0,
            signed=False,
        ),
        "USERIDL": FieldPosition(
            offset=100,
            length=2,
            category="ALPHANUMERIC",
            total_digits=2,
            decimal_digits=0,
            signed=False,
        ),
        "EIBAID": FieldPosition(
            offset=200,
            length=1,
            category="ALPHANUMERIC",
            total_digits=1,
            decimal_digits=0,
            signed=False,
        ),
    }
    region = bytearray(b"\x40" * 210)
    vm = _FakeVM(region, layout)
    monkeypatch.setattr("cics.builtins.system._get_ws_region_addr", lambda _vm: 1)
    vm.region_set = lambda addr, data: region.__setitem__(slice(0, len(data)), data)
    iq: queue.Queue = queue.Queue()
    iq.put(_InputEvent({"USERID": "USER0001"}))
    builtin = make_receive_map_builtin(iq, _AT_TERMINAL, [None], timeout=1.0)
    builtin([_tv("COSGN0A"), _tv(["USERID"])], vm)
    assert bytes(region[0:8]) == "USER0001".encode("cp037")
    assert struct.unpack(">h", bytes(region[100:102]))[0] == 8


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_receive_map_numeric_field_is_de_edited(monkeypatch):
    """A numeric input field (PIC 9 DISPLAY, e.g. from a BMS PICIN='9(n)';
    category ZONED_DECIMAL) is de-edited like z/OS BMS: right-justified and
    zero-filled. An alphanumeric field stays left-justified, space-padded."""
    import struct

    layout = {
        "AMOUNTI": FieldPosition(
            offset=0,
            length=10,
            category="ZONED_DECIMAL",
            total_digits=10,
            decimal_digits=0,
            signed=False,
        ),
        "AMOUNTL": FieldPosition(
            offset=20,
            length=2,
            category="ALPHANUMERIC",
            total_digits=2,
            decimal_digits=0,
            signed=False,
        ),
        "NAMEI": FieldPosition(
            offset=30,
            length=10,
            category="ALPHANUMERIC",
            total_digits=10,
            decimal_digits=0,
            signed=False,
        ),
        "EIBAID": FieldPosition(
            offset=200,
            length=1,
            category="ALPHANUMERIC",
            total_digits=1,
            decimal_digits=0,
            signed=False,
        ),
    }
    region = bytearray(b"\x40" * 210)
    vm = _FakeVM(region, layout)
    monkeypatch.setattr("cics.builtins.system._get_ws_region_addr", lambda _vm: 1)
    vm.region_set = lambda addr, data: region.__setitem__(slice(0, len(data)), data)
    iq: queue.Queue = queue.Queue()
    iq.put(_InputEvent({"AMOUNT": "100", "NAME": "BOB"}))
    builtin = make_receive_map_builtin(iq, _AT_TERMINAL, [None], timeout=1.0)
    builtin([_tv("M"), _tv(["AMOUNT", "NAME"])], vm)

    # Numeric: "100" -> right-justified, zero-filled.
    assert bytes(region[0:10]) == "0000000100".encode("cp037")
    # The numeric field's length halfword still records the entered length.
    assert struct.unpack(">h", bytes(region[20:22]))[0] == 3
    # Alphanumeric: "BOB" -> left-justified, space-padded.
    assert bytes(region[30:40]) == "BOB".ljust(10).encode("cp037")


def _receive(monkeypatch, layout, event, bases):
    region = bytearray(b"\x40" * 64)
    vm = _FakeVM(region, layout)
    monkeypatch.setattr("cics.builtins.system._get_ws_region_addr", lambda _vm: 1)
    vm.region_set = lambda addr, data: region.__setitem__(slice(0, len(data)), data)
    iq: queue.Queue = queue.Queue()
    iq.put(event)
    make_receive_map_builtin(iq, _AT_TERMINAL, [None], timeout=1.0)(
        [_tv("M"), _tv(bases)], vm
    )
    return region


_RECEIVE_LAYOUT = {
    "USERIDL": FieldPosition(
        offset=0,
        length=2,
        category="ALPHANUMERIC",
        total_digits=2,
        decimal_digits=0,
        signed=False,
    ),
    "USERIDF": FieldPosition(
        offset=2,
        length=1,
        category="ALPHANUMERIC",
        total_digits=1,
        decimal_digits=0,
        signed=False,
    ),
    "USERIDI": FieldPosition(
        offset=3,
        length=8,
        category="ALPHANUMERIC",
        total_digits=8,
        decimal_digits=0,
        signed=False,
    ),
    "PASSWDL": FieldPosition(
        offset=11,
        length=2,
        category="ALPHANUMERIC",
        total_digits=2,
        decimal_digits=0,
        signed=False,
    ),
    "PASSWDF": FieldPosition(
        offset=13,
        length=1,
        category="ALPHANUMERIC",
        total_digits=1,
        decimal_digits=0,
        signed=False,
    ),
    "PASSWDI": FieldPosition(
        offset=14,
        length=8,
        category="ALPHANUMERIC",
        total_digits=8,
        decimal_digits=0,
        signed=False,
    ),
    "EIBAID": FieldPosition(
        offset=40,
        length=1,
        category="ALPHANUMERIC",
        total_digits=1,
        decimal_digits=0,
        signed=False,
    ),
    "EIBCPOSN": FieldPosition(
        offset=41,
        length=2,
        category="ALPHANUMERIC",
        total_digits=2,
        decimal_digits=0,
        signed=False,
    ),
}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unreceived_fields_are_low_values_with_zero_length(monkeypatch):
    region = _receive(
        monkeypatch,
        _RECEIVE_LAYOUT,
        InputEvent(fields={"USERID": "U1"}),
        ["USERID", "PASSWD"],
    )
    assert region[14:22] == b"\x00" * 8
    assert struct.unpack(">h", region[11:13])[0] == 0
    assert region[13] == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_received_empty_field_sets_the_cleared_flag(monkeypatch):
    region = _receive(
        monkeypatch, _RECEIVE_LAYOUT, InputEvent(fields={"USERID": ""}), ["USERID"]
    )
    assert (struct.unpack(">h", region[0:2])[0], region[2]) == (0, 0x80)


_NUMERIC_RECEIVE_LAYOUT = {
    "AMOUNTL": FieldPosition(
        offset=0,
        length=2,
        category="ALPHANUMERIC",
        total_digits=2,
        decimal_digits=0,
        signed=False,
    ),
    "AMOUNTF": FieldPosition(
        offset=2,
        length=1,
        category="ALPHANUMERIC",
        total_digits=1,
        decimal_digits=0,
        signed=False,
    ),
    "AMOUNTI": FieldPosition(
        offset=3,
        length=10,
        category="ZONED_DECIMAL",
        total_digits=10,
        decimal_digits=0,
        signed=False,
    ),
    "EIBAID": FieldPosition(
        offset=40,
        length=1,
        category="ALPHANUMERIC",
        total_digits=1,
        decimal_digits=0,
        signed=False,
    ),
    "EIBCPOSN": FieldPosition(
        offset=41,
        length=2,
        category="ALPHANUMERIC",
        total_digits=2,
        decimal_digits=0,
        signed=False,
    ),
}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_received_empty_numeric_field_is_zero_filled_not_blank(monkeypatch):
    """Pins CURRENT behaviour for a numeric (BMS PICIN='9(n)', category
    ZONED_DECIMAL) field the terminal transmits with zero length — MDT set,
    operator left it blank. <f>I is zero-filled across its whole declared
    length (not left at low-values/spaces), <f>L is 0, and <f>F carries the
    cleared flag, exactly as for a blank alphanumeric field. See
    ``_received_writes`` in cics/builtins/screen.py: this is deliberate,
    matching documented z/OS BMS numeric de-editing of an empty field."""
    region = _receive(
        monkeypatch,
        _NUMERIC_RECEIVE_LAYOUT,
        InputEvent(fields={"AMOUNT": ""}),
        ["AMOUNT"],
    )
    assert bytes(region[3:13]) == "0000000000".encode("cp037")
    assert struct.unpack(">h", region[0:2])[0] == 0
    assert region[2] == 0x80


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_received_field_length_and_eibcposn(monkeypatch):
    region = _receive(
        monkeypatch,
        _RECEIVE_LAYOUT,
        InputEvent(fields={"USERID": "U1"}, cursor=Cursor(1483)),
        ["USERID"],
    )
    assert (
        struct.unpack(">h", region[0:2])[0],
        region[2],
        region[3:5].decode("cp037"),
    ) == (2, 0, "U1")
    assert struct.unpack(">h", region[41:43])[0] == 1483


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_text_enqueues_text():
    screen_q: queue.Queue = queue.Queue()
    builtin = make_send_text_builtin(screen_q)
    args = [typed("Hello, world!", UNKNOWN)]
    result = builtin(args, VMState())
    assert isinstance(result, BuiltinResult)
    item = screen_q.get(block=False)
    assert item["type"] == "text"
    assert "Hello" in item["text"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_receive_map_in_a_non_terminal_task_is_invreq_and_consumes_no_input():
    """A task started with no TERMID has no screen to read: RECEIVE MAP is INVREQ
    and must leave the terminal's pending input for the task that owns it."""
    iq: queue.Queue = queue.Queue()
    pending = InputEvent(eibaid="\x33", fields={"USERID": "ALICE"})
    iq.put(pending)
    builtin = make_receive_map_builtin(iq, _NO_TERMINAL_TASK, [None], timeout=1.0)

    result = builtin([_tv("COSGN0A"), _tv(["USERID"])], _FakeVM(bytearray(210), {}))

    assert result.value == 16  # DFHRESP(INVREQ)
    assert iq.qsize() == 1
    assert iq.get_nowait() is pending


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_map_in_a_non_terminal_task_is_invreq_and_writes_no_screen():
    """The SEND side of the same rule, at the builtin level."""
    sq: queue.Queue = queue.Queue()
    builtin = make_send_map_builtin(sq, _NO_TERMINAL_TASK)

    result = builtin([_tv("COSGN0A"), _tv(["USERID"])], _FakeVM(bytearray(210), {}))

    assert result.value == 16  # DFHRESP(INVREQ)
    assert sq.qsize() == 0


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_receive_map_that_times_out_does_not_report_normal():
    """A read that gets no input filled nothing: EIBRESP must not say NORMAL, and
    the region must see the read-timeout abend CICS raises on RTIMOUT expiry."""
    result_holder: list = [None]
    builtin = make_receive_map_builtin(
        queue.Queue(), _AT_TERMINAL, result_holder, timeout=0.01
    )

    result = builtin([_tv("COSGN0A"), _tv(["USERID"])], _FakeVM(bytearray(210), {}))

    assert result.value == 36  # DFHRESP(MAPFAIL) — nothing was mapped in
    assert result_holder[0].kind == DispatchKind.ABEND
    assert result_holder[0].abcode == "AZCT"
