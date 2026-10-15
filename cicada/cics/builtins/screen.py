"""BMS screen builtins: SEND MAP, RECEIVE MAP, SEND TEXT."""

from __future__ import annotations

import logging
import queue
import struct
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from cics.builtins.cells import FieldWrite, commit_region, write_fields
from cics.cell import Holder, held_or, hold
from cics.input_event import DFHENTER, InputEvent
from cics.screen.cursor import NO_CURSOR, Cursor, CursorPosition, SymbolicCursor
from cics.screen.payload import FieldAttributes, SendMapPayload, SendMode
from cics.terminal import InputChannel, ScreenChannel
from cics.types import NO_TERMINAL, CicsContext, DispatchKind, DispatchResult
from interpreter.address import Address
from interpreter.cobol.field_position import FieldPosition
from interpreter.cobol.layout_data import field_positions
from interpreter.types.typed_value import TypedValue
from interpreter.vm.vm_types import BuiltinResult, VMState

logger = logging.getLogger(__name__)

# Field category (CobolDataCategory.ZONED_DECIMAL.value) for a PIC 9
# DISPLAY field — what a BMS PICIN='9(n)' input field generates. Such fields are
# de-edited on RECEIVE (right-justified, zero-filled), as z/OS BMS does.
_NUMERIC_DISPLAY = "ZONED_DECIMAL"

# DFHRESP values written back into EIBRESP by the BMS verbs.
_RESP_NORMAL = 0
_RESP_INVREQ = 16
_RESP_MAPFAIL = 36

# A terminal read that never gets input is RTIMOUT expiry: CICS purges the task
# with abend AZCT, the same abcode _run_dispatcher_with_runner reports when its
# own wait for input times out.
_READ_TIMEOUT_ABCODE = "AZCT"

# <f>F attribute-byte flag set when a field's data was cleared (received empty).
_FLAG_CLEARED = 0x80

_CP037_SPACE = " ".encode("cp037")  # 0x40
_CP037_ZERO = "0".encode("cp037")  # 0xF0

_NO_CONTEXT = CicsContext(transid="", commarea=b"", eibaid=DFHENTER, termid=NO_TERMINAL)

CicsBuiltin = Callable[[Sequence[TypedValue], VMState], BuiltinResult]


@dataclass(frozen=True)
class WsRegion:
    address: Address
    data: bytearray


NO_WS_REGION = WsRegion(address=Address(""), data=bytearray())


def ws_region(vm: VMState) -> WsRegion:
    """The working-storage region, or NO_WS_REGION when the VM has none."""
    from cics.builtins.system import _get_ws_region_addr

    address = _get_ws_region_addr(vm)
    if not address:
        return NO_WS_REGION
    region = vm.region_get(address)
    return WsRegion(address, region) if region else NO_WS_REGION


def read_ws_field(
    positions: Mapping[str, FieldPosition], region: bytearray, name: str
) -> bytes:
    if name not in positions:
        return b""
    position = positions[name]
    return bytes(region[position.offset : position.offset + position.length])


def _numeric_input(positions: Mapping[str, FieldPosition], name: str) -> bool:
    return name in positions and positions[name].category == _NUMERIC_DISPLAY


def _has_terminal(context_holder: Holder[CicsContext]) -> bool:
    """A task started with no TERMID has no terminal; CICS makes terminal I/O
    invalid for it rather than writing to some other user's screen."""
    return bool(held_or(context_holder, _NO_CONTEXT).termid)


def _map_name(args: Sequence[TypedValue], idx: int = 0) -> str:
    return str(args[idx].value).strip("'\" ") if len(args) > idx else ""


def _named_args(args: Sequence[TypedValue], idx: int) -> tuple[str, ...]:
    return (
        tuple(args[idx].value)
        if len(args) > idx and isinstance(args[idx].value, list)
        else ()
    )


_MODE_OPTIONS = (("MAPONLY", SendMode.MAPONLY), ("DATAONLY", SendMode.DATAONLY))


def _cursor_arg(args: Sequence[TypedValue], index: int) -> int:
    text = str(args[index].value).strip() if len(args) > index else ""
    return int(text) if text.lstrip("-").isdigit() else -1


def _send_mode(flags: frozenset[str]) -> SendMode:
    return next(
        (mode for option, mode in _MODE_OPTIONS if option in flags), SendMode.FULL
    )


def _halfword(
    positions: Mapping[str, FieldPosition], region: bytearray, name: str
) -> int:
    raw = read_ws_field(positions, region, name)
    return struct.unpack(">h", raw)[0] if len(raw) == 2 else 0


def _byte(positions: Mapping[str, FieldPosition], region: bytearray, name: str) -> int:
    raw = read_ws_field(positions, region, name)
    return raw[0] if raw else 0


def _send_cursor(
    positions: Mapping[str, FieldPosition],
    region: bytearray,
    bases: Sequence[str],
    flags: frozenset[str],
    offset: int,
) -> CursorPosition:
    """CURSOR(n) is an offset; a bare CURSOR takes the first field whose <f>L is -1."""
    marked = tuple(b for b in bases if _halfword(positions, region, b + "L") == -1)
    symbolic = SymbolicCursor(marked[0]) if marked else NO_CURSOR
    explicit = Cursor(offset) if offset >= 0 else symbolic
    return explicit if "CURSOR" in flags else NO_CURSOR


def _symbolic_values(
    positions: Mapping[str, FieldPosition], region: bytearray, bases: Sequence[str]
) -> Mapping[str, str]:
    raw = {b: read_ws_field(positions, region, b + "O") for b in bases}
    return {
        b: data.decode("cp037", errors="replace").rstrip()
        for b, data in raw.items()
        if data
    }


def _overrides(
    positions: Mapping[str, FieldPosition], region: bytearray, bases: Sequence[str]
) -> Mapping[str, FieldAttributes]:
    attrs = {
        b: FieldAttributes(
            _byte(positions, region, b + "A"),
            _byte(positions, region, b + "C"),
            _byte(positions, region, b + "H"),
        )
        for b in bases
    }
    return {b: a for b, a in attrs.items() if a.overrides}


def _send_map_payload(args: Sequence[TypedValue], vm: VMState) -> SendMapPayload:
    bases = tuple(str(v) for v in _named_args(args, 1))
    flags = frozenset(str(v) for v in _named_args(args, 3))
    region = ws_region(vm).data
    positions = field_positions(vm.declarations)
    mode = _send_mode(flags)
    symbolic = mode is not SendMode.MAPONLY
    return SendMapPayload(
        map=_map_name(args, 0),
        mapset=_map_name(args, 2),
        mode=mode,
        erase="ERASE" in flags,
        alarm="ALARM" in flags,
        frset="FRSET" in flags,
        freekb="FREEKB" in flags,
        cursor=_send_cursor(positions, region, bases, flags, _cursor_arg(args, 4)),
        fields=_symbolic_values(positions, region, bases) if symbolic else {},
        attrs=_overrides(positions, region, bases) if symbolic else {},
    )


def make_send_map_builtin(
    screen_queue: ScreenChannel, context_holder: Holder[CicsContext]
) -> CicsBuiltin:
    def __cics_send_map(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        if not _has_terminal(context_holder):
            return BuiltinResult(value=_RESP_INVREQ)
        screen_queue.put(_send_map_payload(args, vm).to_message())
        return BuiltinResult(value=_RESP_NORMAL)

    return __cics_send_map


def _event_fields(item: InputEvent | Mapping[str, str]) -> Mapping[str, str]:
    if isinstance(item, InputEvent):
        return item.fields
    # A legacy queue producer's bare object (``.fields``/``.eibaid``, no
    # InputEvent) reads the same as a real one; only a plain dict is the field
    # map itself.
    return getattr(item, "fields", item)


def _event_aid(item: InputEvent | Mapping[str, str]) -> str:
    if isinstance(item, InputEvent):
        return item.eibaid
    return getattr(item, "eibaid", DFHENTER)


def _event_cursor(item: InputEvent | Mapping[str, str]) -> CursorPosition:
    if isinstance(item, InputEvent):
        return item.cursor
    return getattr(item, "cursor", NO_CURSOR)


def _encoded(value: str | bytes) -> bytes:
    return (
        value if isinstance(value, bytes) else value.encode("cp037", errors="replace")
    )


def _received_writes(
    positions: Mapping[str, FieldPosition], base: str, raw: bytes
) -> tuple[FieldWrite, ...]:
    """The write set for a field the terminal actually sent: its <f>I data
    (numeric input fields — BMS PICIN '9(n)' -> PIC 9 DISPLAY, category
    ZONED_DECIMAL — de-edited like z/OS BMS, right-justified and zero-filled;
    other fields left-justified and space-padded), its <f>L entered length,
    and its <f>F attribute byte, flagged cleared when the field arrived empty."""
    numeric = _numeric_input(positions, base + "I")
    data = (
        FieldWrite(base + "I", raw, _CP037_ZERO, True)
        if numeric
        else FieldWrite(base + "I", raw, _CP037_SPACE)
    )
    flag = bytes((0 if raw else _FLAG_CLEARED,))
    return (
        data,
        FieldWrite(base + "L", struct.pack(">h", len(raw))),
        FieldWrite(base + "F", flag),
    )


def _unreceived_writes(base: str) -> tuple[FieldWrite, ...]:
    """A base the terminal did not send: real BMS leaves it at low-values with
    zero length, not whatever WS held before."""
    return (
        FieldWrite(base + "I", b""),
        FieldWrite(base + "L", struct.pack(">h", 0)),
        FieldWrite(base + "F", b"\x00"),
    )


def _field_writes(
    positions: Mapping[str, FieldPosition], base: str, values: Mapping[str, str]
) -> tuple[FieldWrite, ...]:
    if base not in values:
        return _unreceived_writes(base)
    return _received_writes(positions, base, _encoded(values[base]))


def _apply_input_writes(
    positions: Mapping[str, FieldPosition],
    item: InputEvent | Mapping[str, str],
    base_names: frozenset[str],
) -> tuple[FieldWrite, ...]:
    """Write a terminal input event (real or legacy-duck-typed, or a plain
    dict) into the WS region: EIBAID, EIBCPOSN, then every base in the map —
    received bases get their <f>I/<f>L/<f>F per ``_received_writes``,
    unreceived bases are cleared to low-values per ``_unreceived_writes``, the
    same as real BMS. Shared by the blocking RECEIVE builtin
    (pseudo-conversational) and the suspend-driven apply-input builtin."""
    aid = _event_aid(item)
    aid_byte = ord(aid) if aid else ord(DFHENTER)
    eibaid_write = FieldWrite(name="EIBAID", data=bytes([aid_byte]))
    cposn_write = FieldWrite(
        "EIBCPOSN", struct.pack(">h", _event_cursor(item).eibcposn())
    )
    values = _event_fields(item)
    return (
        eibaid_write,
        cposn_write,
        *(
            w
            for base in sorted(base_names)
            for w in _field_writes(positions, base, values)
        ),
    )


def _apply_input(
    vm: VMState, item: InputEvent | Mapping[str, str], base_names: frozenset[str]
) -> None:
    region = ws_region(vm)
    if not region.data:
        logger.warning("RECEIVE MAP: no WS region — EIBAID not updated")
        return
    positions = field_positions(vm.declarations)
    missing = write_fields(
        positions, region.data, _apply_input_writes(positions, item, base_names)
    )
    commit_region(vm, region.address, region.data)
    if "EIBAID" in missing:
        logger.warning("RECEIVE MAP: EIBAID not in data layout — EIBAID not updated")


@dataclass(frozen=True)
class _ReadTimedOut:
    """The input queue produced nothing within the RECEIVE MAP deadline."""


_READ_TIMED_OUT = _ReadTimedOut()


def _read_input(
    input_queue: InputChannel, timeout: float
) -> InputEvent | Mapping[str, str] | _ReadTimedOut:
    try:
        return input_queue.get(timeout=timeout)
    except queue.Empty:
        return _READ_TIMED_OUT


def _finish_receive_map(
    vm: VMState,
    item: InputEvent | Mapping[str, str] | _ReadTimedOut,
    base_names: frozenset[str],
    result_holder: Holder[DispatchResult],
) -> BuiltinResult:
    if isinstance(item, _ReadTimedOut):
        logger.warning(
            "RECEIVE MAP: timeout waiting for input — %s", _READ_TIMEOUT_ABCODE
        )
        hold(
            result_holder,
            DispatchResult(kind=DispatchKind.ABEND, abcode=_READ_TIMEOUT_ABCODE),
        )
        return BuiltinResult(value=_RESP_MAPFAIL)
    _apply_input(vm, item, base_names)
    return BuiltinResult(value=_RESP_NORMAL)


def make_receive_map_builtin(
    input_queue: InputChannel,
    context_holder: Holder[CicsContext],
    result_holder: Holder[DispatchResult],
    timeout: float = 30.0,
) -> CicsBuiltin:
    """Pseudo-conversational RECEIVE MAP: block on the input queue for one event,
    then apply it. (Conversational mode lowers RECEIVE to SUSPEND + apply-input.)

    A read that times out reports MAPFAIL and records the AZCT abend: the INTO
    area was not filled, so EIBRESP must not say NORMAL, and a program that codes
    no RESP would otherwise carry on over a map it never received. The builtin
    cannot itself end the task, hence both — the resp for the program, the
    result_holder abend for the region.
    """

    def __cics_receive_map(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        if not _has_terminal(context_holder):
            return BuiltinResult(value=_RESP_INVREQ)
        item = _read_input(input_queue, timeout)
        base_names = frozenset(_named_args(args, 1))
        return _finish_receive_map(vm, item, base_names, result_holder)

    return __cics_receive_map


def make_apply_input_builtin() -> CicsBuiltin:
    """Conversational RECEIVE MAP tail: apply the InputEvent the driver injected at
    the SUSPEND (args[0]) to the WS region. args[1] is the field base-name list.

    Returns an EIBRESP code, like the blocking RECEIVE MAP builtin: the same
    source must not behave differently in conversational mode. No event at the
    resume means the INTO area was never filled, which is MAPFAIL."""

    def __cics_apply_input(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        has_event = bool(args) and bool(args[0].value)
        if has_event:
            _apply_input(vm, args[0].value, frozenset(_named_args(args, 1)))
        return BuiltinResult(value=_RESP_NORMAL if has_event else _RESP_MAPFAIL)

    return __cics_apply_input


def make_send_text_builtin(screen_queue: ScreenChannel) -> CicsBuiltin:
    def __cics_send_text(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        text = str(args[0].value) if args else ""
        screen_queue.put({"type": "text", "text": text})
        return BuiltinResult(value=None)

    return __cics_send_text
