"""CICS interval-control builtins — START, closed over a StartQueue."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cics.interval import RejectReason, StartQueue, StartRequest
from interpreter.vm.vm_types import BuiltinResult, VMState

if TYPE_CHECKING:
    from interpreter.types.typed_value import TypedValue

logger = logging.getLogger(__name__)

_RESP_NORMAL = 0
_RESP_TERMIDERR = 11
_RESP_TRANSIDERR = 28


def _text(args: list[TypedValue], i: int) -> str:
    return str(args[i].value).strip("'\" ") if len(args) > i else ""


def _payload(args: list[TypedValue], i: int) -> bytes:
    v = args[i].value if len(args) > i else b""
    return (
        bytes(v)
        if isinstance(v, (bytes, bytearray, list))
        else str(v).encode("cp037", "replace")
    )


def make_start_builtin(
    start_queue: StartQueue,
    transid_to_program: dict[str, str],
    region_termid: str,
) -> object:
    """START: queues a start-request and returns a resp code.

    args: (transid_str, data_bytes, termid_str, reqid_str, timing_str)

    Deliberately does NOT end the task — the lowering emits no Return_, so the
    issuing program falls through to its next statement as in real CICS.
    """

    def __cics_start(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        req = StartRequest(
            transid=_text(args, 0),
            data=_payload(args, 1),
            termid=_text(args, 2),
            reqid=_text(args, 3),
            timing_text=_text(args, 4),
        )
        if req.transid not in transid_to_program:
            start_queue.reject(req, RejectReason.UNKNOWN_TRANSID)
            return BuiltinResult(value=_RESP_TRANSIDERR)
        if req.termid not in ("", region_termid):
            start_queue.reject(req, RejectReason.NO_SUCH_TERMINAL)
            return BuiltinResult(value=_RESP_TERMIDERR)
        start_queue.queue(req)
        return BuiltinResult(value=_RESP_NORMAL)

    return __cics_start
