"""BMS screen builtins: SEND MAP, RECEIVE MAP, SEND TEXT."""

from __future__ import annotations

import logging
import queue
import struct
from typing import Any

from cics.terminal import InputChannel, ScreenChannel
from cics.types import DispatchKind, DispatchResult
from interpreter.types.typed_value import TypedValue
from interpreter.vm.vm_types import BuiltinResult, VMState

logger = logging.getLogger(__name__)

# data_layout category (CobolDataCategory.ZONED_DECIMAL.value) for a PIC 9
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


def _has_terminal(context_holder: list) -> bool:
    """A task started with no TERMID has no terminal; CICS makes terminal I/O
    invalid for it rather than writing to some other user's screen."""
    ctx = context_holder[0]
    return bool(ctx) and bool(ctx.termid)


def _map_name(args: list[TypedValue], idx: int = 0) -> str:
    return str(args[idx].value).strip("'\" ") if len(args) > idx else ""


def _ws_region(vm: VMState):
    """Locate the (addr, region bytearray) for the WS region, or (None, None).

    Mirrors ``make_init_eib_builtin``: the WS region address lives in the
    ``__ws_region`` local var and its bytes in ``vm.region_get``.
    """
    from cics.builtins.system import _get_ws_region_addr

    if vm is None:
        return None, None
    addr = _get_ws_region_addr(vm)
    if addr is None:
        return None, None
    region = vm.region_get(addr)
    if region is None:
        return None, None
    return addr, region


def _read_ws_field(vm: VMState, region, name: str) -> bytes | None:
    """Read a named field's bytes from the WS region via vm.data_layout."""
    f = vm.data_layout.get(name)
    if f is None:
        return None
    off, length = f["offset"], f["length"]
    return bytes(region[off : off + length])


def _write_ws_field(
    vm: VMState,
    region,
    name: str,
    data: bytes,
    pad: bytes = b"\x00",
    right_justify: bool = False,
) -> bool:
    """Write data into a named field in the WS region via vm.data_layout.

    Truncates/pads to the field length (pad byte defaults to NUL; pass the
    cp037 space for alphanumeric fields). ``right_justify`` right-aligns the data
    and fills on the left (used to de-edit numeric input fields). Returns True if
    the field was present in the layout and written.
    """
    f = vm.data_layout.get(name)
    if f is None:
        return False
    off, length = f["offset"], f["length"]
    clipped = data[:length]
    placed = clipped.rjust(length, pad) if right_justify else clipped.ljust(length, pad)
    region[off : off + length] = placed[:length]
    return True


def make_send_map_builtin(screen_queue: ScreenChannel, context_holder: list) -> object:
    def __cics_send_map(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        if not _has_terminal(context_holder):
            return BuiltinResult(value=_RESP_INVREQ)
        map_name = _map_name(args, 0)
        base_names = (
            list(args[1].value)
            if len(args) > 1 and isinstance(args[1].value, list)
            else []
        )
        _addr, ws = _ws_region(vm)
        symbolic: dict[str, str] = {}
        if ws is not None:
            for base in base_names:
                raw = _read_ws_field(vm, ws, base + "O")
                if raw is not None:
                    symbolic[base] = raw.decode("cp037", errors="replace").rstrip()
        screen_queue.put({"map": map_name, "fields": symbolic})
        return BuiltinResult(value=_RESP_NORMAL)

    return __cics_send_map


_DFHENTER = "\x7d"


def _write_eibaid(vm: VMState, aid: str) -> None:
    """Write the attention id into the EIB's EIBAID field in the WS region.

    Mirrors ``make_init_eib_builtin``'s single-byte EIBAID write. Missing WS
    region or no EIBAID in the data layout → log + skip (non-fatal).
    """
    addr, region = _ws_region(vm)
    if region is None:
        logger.warning("RECEIVE MAP: no WS region — EIBAID not updated")
        return
    assert addr is not None  # region non-None implies addr non-None (_ws_region)
    aid_byte = ord(aid) if aid else 0x7D
    if _write_ws_field(vm, region, "EIBAID", bytes([aid_byte])):
        vm.region_set(addr, region)
    else:
        logger.warning("RECEIVE MAP: EIBAID not in data layout — EIBAID not updated")


def _apply_input(vm: VMState, item: Any, base_names: set) -> None:
    """Write a terminal input event (``.fields`` + ``.eibaid``, or a plain dict)
    into the WS region: EIBAID, then each named input field. Numeric input fields
    (BMS PICIN '9(n)' -> PIC 9 DISPLAY, category ZONED_DECIMAL) are de-edited like
    z/OS BMS — right-justified, zero-filled; default X(n) fields land
    left-justified, space-padded. Shared by the blocking RECEIVE builtin
    (pseudo-conversational) and the suspend-driven apply-input builtin."""
    field_values: dict[str, bytes | str] = getattr(item, "fields", item) or {}
    aid: str = getattr(item, "eibaid", _DFHENTER)
    _write_eibaid(vm, aid)

    addr, ws = _ws_region(vm)
    if ws is None:
        return
    cp037_space = " ".encode("cp037")  # 0x40
    cp037_zero = "0".encode("cp037")  # 0xF0
    for base, v in field_values.items():
        if base not in base_names:
            continue
        raw = v if isinstance(v, bytes) else v.encode("cp037", errors="replace")
        name = base + "I"
        category = (vm.data_layout.get(name) or {}).get("category")
        if category == _NUMERIC_DISPLAY:
            wrote = _write_ws_field(
                vm, ws, name, raw, pad=cp037_zero, right_justify=True
            )
        else:
            wrote = _write_ws_field(vm, ws, name, raw, pad=cp037_space)
        if wrote:
            _write_ws_field(vm, ws, base + "L", struct.pack(">h", len(raw)))
    assert addr is not None  # ws non-None implies addr non-None
    vm.region_set(addr, ws)


def _base_names(args: list[TypedValue], idx: int) -> set:
    return (
        set(args[idx].value)
        if len(args) > idx and isinstance(args[idx].value, list)
        else set()
    )


def make_receive_map_builtin(
    input_queue: InputChannel,
    context_holder: list,
    result_holder: list,
    timeout: float = 30.0,
) -> object:
    """Pseudo-conversational RECEIVE MAP: block on the input queue for one event,
    then apply it. (Conversational mode lowers RECEIVE to SUSPEND + apply-input.)

    A read that times out reports MAPFAIL and records the AZCT abend: the INTO
    area was not filled, so EIBRESP must not say NORMAL, and a program that codes
    no RESP would otherwise carry on over a map it never received. The builtin
    cannot itself end the task, hence both — the resp for the program, the
    result_holder abend for the region.
    """

    def __cics_receive_map(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        if not _has_terminal(context_holder):
            return BuiltinResult(value=_RESP_INVREQ)
        base_names = _base_names(args, 1)
        try:
            item: Any = input_queue.get(timeout=timeout)
        except queue.Empty:
            logger.warning(
                "RECEIVE MAP: timeout waiting for input — %s", _READ_TIMEOUT_ABCODE
            )
            result_holder[0] = DispatchResult(
                kind=DispatchKind.ABEND, abcode=_READ_TIMEOUT_ABCODE
            )
            return BuiltinResult(value=_RESP_MAPFAIL)
        _apply_input(vm, item, base_names)
        return BuiltinResult(value=_RESP_NORMAL)

    return __cics_receive_map


def make_apply_input_builtin() -> object:
    """Conversational RECEIVE MAP tail: apply the InputEvent the driver injected at
    the SUSPEND (args[0]) to the WS region. args[1] is the field base-name list.

    Returns an EIBRESP code, like the blocking RECEIVE MAP builtin: the same
    source must not behave differently in conversational mode. No event at the
    resume means the INTO area was never filled, which is MAPFAIL."""

    def __cics_apply_input(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        events = [args[0].value] if args and args[0].value else []
        for item in events:
            _apply_input(vm, item, _base_names(args, 1))
        return BuiltinResult(value=_RESP_NORMAL if events else _RESP_MAPFAIL)

    return __cics_apply_input


def make_send_text_builtin(screen_queue: ScreenChannel) -> object:
    def __cics_send_text(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        text = str(args[0].value) if args else ""
        screen_queue.put({"type": "text", "text": text})
        return BuiltinResult(value=None)

    return __cics_send_text
