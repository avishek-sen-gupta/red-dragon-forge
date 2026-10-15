"""CICS interval-control builtins — START, closed over a StartQueue."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from cics.builtins.cells import commit_region, write_at
from cics.builtins.screen import CicsBuiltin, ws_region
from cics.interval import RejectReason, StartQueue, StartRequest
from cics.types import NO_TERMINAL
from interpreter.types.typed_value import TypedValue
from interpreter.vm.vm_types import BuiltinResult, VMState

logger = logging.getLogger(__name__)

_RESP_NORMAL = 0
_RESP_TERMIDERR = 11
_RESP_TRANSIDERR = 28
_RESP_ENDDATA = 29


def _text(args: Sequence[TypedValue], i: int) -> str:
    return str(args[i].value).strip("'\" ") if len(args) > i else ""


def _payload(args: Sequence[TypedValue], i: int) -> bytes:
    v = args[i].value if len(args) > i else b""
    return (
        bytes(v)
        if isinstance(v, (bytes, bytearray, list))
        else str(v).encode("cp037", "replace")
    )


def _start(
    start_queue: StartQueue,
    transid_to_program: Mapping[str, str],
    region_termid: str,
    req: StartRequest,
) -> int:
    if req.transid not in transid_to_program:
        start_queue.reject(req, RejectReason.UNKNOWN_TRANSID)
        return _RESP_TRANSIDERR
    if req.termid not in (NO_TERMINAL, region_termid):
        start_queue.reject(req, RejectReason.NO_SUCH_TERMINAL)
        return _RESP_TERMIDERR
    start_queue.queue(req)
    return _RESP_NORMAL


def make_start_builtin(
    start_queue: StartQueue,
    transid_to_program: Mapping[str, str],
    region_termid: str,
) -> CicsBuiltin:
    """START: queues a start-request and returns a resp code.

    args: (transid_str, data_bytes, termid_str, reqid_str, timing_str)

    Deliberately does NOT end the task — the lowering emits no Return_, so the
    issuing program falls through to its next statement as in real CICS.
    """

    def __cics_start(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        req = StartRequest(
            transid=_text(args, 0),
            data=_payload(args, 1),
            termid=_text(args, 2),
            reqid=_text(args, 3),
            timing_text=_text(args, 4),
        )
        return BuiltinResult(
            value=_start(start_queue, transid_to_program, region_termid, req)
        )

    return __cics_start


def _write_into_ws(vm: VMState, data: bytes, offset: int, length: int) -> None:
    """Write ``data`` into the WORKING-STORAGE region at the INTO field's offset.

    Same Option-A buffer fill as the VSAM read builtins; see cics/builtins/vsam.py.
    """
    region = ws_region(vm)
    if not region.data:
        logger.warning("RETRIEVE: no WS region in VM — INTO not filled")
        return
    write_at(region.data, offset, data[:length].ljust(length, b"\x00"))
    commit_region(vm, region.address, region.data)


def make_retrieve_builtin(start_queue: StartQueue) -> CicsBuiltin:
    """RETRIEVE: consumes this task's start data into INTO; returns a resp code.

    args: (into_offset_int, into_length_int)

    ENDDATA when there is no start data — the normal case for a task entered from
    the terminal rather than by START. The INTO area is then left untouched.
    """

    def __cics_retrieve(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        into_off = int(args[0].value) if args else 0
        into_len = int(args[1].value) if len(args) > 1 else 0
        data = start_queue.take_start_data()
        if not data:
            return BuiltinResult(value=_RESP_ENDDATA)
        _write_into_ws(vm, data[0], into_off, into_len)
        return BuiltinResult(value=_RESP_NORMAL)

    return __cics_retrieve
