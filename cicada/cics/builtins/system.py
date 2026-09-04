"""CICS system service builtins — curried closures over shared state."""

from __future__ import annotations

import logging
import struct
from typing import TYPE_CHECKING

from interpreter.vm.vm_types import BuiltinResult, VMState
from interpreter.types.typed_value import TypedValue
from interpreter.var_name import VarName
from interpreter.address import Address
from cics.conditions import UNHANDLED_ABCODE, UNSUPPORTED_VERB_ABCODE
from cics.types import DispatchKind, DispatchResult

if TYPE_CHECKING:
    from cics.types import CicsContext

logger = logging.getLogger(__name__)

_RESP_NORMAL = 0  # DFHRESP(NORMAL) — nothing went wrong
_RESP_PGMIDERR = 27  # DFHRESP(PGMIDERR) — INQUIRE's "program not found"


def _ascii_to_ebcdic_bytes(s: str, length: int) -> list[int]:
    from interpreter.cobol.ebcdic_table import EbcdicTable

    padded = s.ljust(length)[:length]
    return [
        EbcdicTable.ASCII_TO_EBCDIC[ord(c)] if ord(c) < 256 else 0x40 for c in padded
    ]


def _get_ws_region_addr(vm: VMState) -> Address | None:
    ws_var = VarName("__ws_region")
    for frame in reversed(vm.call_stack):
        if ws_var in frame.local_vars:
            tv = frame.local_vars[ws_var]
            return Address(str(tv.value))
    return None


def make_init_eib_builtin(context_holder: list[CicsContext]) -> object:
    """Return a builtin that writes EIB fields to WS at procedure entry."""

    def __cics_init_eib(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        ctx = context_holder[0]
        addr = _get_ws_region_addr(vm)
        if addr is None:
            logger.warning(
                "__cics_init_eib: no __ws_region in VM — EIB not initialised"
            )
            return BuiltinResult(value=None)

        region = vm.region_get(addr)
        if region is None:
            logger.warning(
                "__cics_init_eib: WS region not allocated — EIB not initialised"
            )
            return BuiltinResult(value=None)

        layout = vm.data_layout

        def _write_field(name: str, data: list[int]) -> None:
            if name not in layout:
                return
            f = layout[name]
            off, length = f["offset"], f["length"]
            region[off : off + length] = data[:length]

        _write_field("EIBTRNID", _ascii_to_ebcdic_bytes(ctx.transid, 4))
        _write_field("EIBTRMID", _ascii_to_ebcdic_bytes(ctx.termid, 4))
        _write_field("EIBCALEN", list(struct.pack(">h", len(ctx.commarea))))
        aid_byte = ord(ctx.eibaid) if ctx.eibaid else 0x7D
        _write_field("EIBAID", [aid_byte])
        _write_field("EIBRESP", list(struct.pack(">i", 0)))
        _write_field("EIBRESP2", list(struct.pack(">i", 0)))
        vm.region_set(addr, region)
        return BuiltinResult(value=None)

    return __cics_init_eib


ASSIGN_SUBOPTIONS = ("APPLID", "SYSID", "USERID")

# The userid CICS reports for a task that has not signed on.
DEFAULT_USERID = "CICSUSER"


def make_assign_builtin(
    applid: str = "CARDDEMO", sysid: str = "SYS1", userid: str = DEFAULT_USERID
) -> object:
    """Return a builtin that yields the value of an ASSIGN output sub-option.

    Called once per sub-option in ``ASSIGN_SUBOPTIONS`` with the key in
    ``args[0]``; returns the configured value so the caller can copy it back into
    the named field. Anything else yields an empty string.
    """

    values: dict[str, str] = dict(zip(ASSIGN_SUBOPTIONS, (applid, sysid, userid)))

    def __cics_assign(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        key = str(args[0].value).strip().upper() if args else ""
        if key and key not in values:
            logger.warning(
                "ASSIGN %s is not implemented — yielding an empty value", key
            )
        return BuiltinResult(value=values.get(key, ""))

    return __cics_assign


def make_asktime_builtin() -> object:
    def __cics_asktime(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        from datetime import datetime, timezone

        epoch_1900 = datetime(1900, 1, 1, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        abstime = int((now - epoch_1900).total_seconds() * 1_000_000)
        return BuiltinResult(value=abstime)

    return __cics_asktime


_DATE_PARTS = {
    "YYYYMMDD": ("%Y", "%m", "%d"),
    "DATE": ("%Y", "%m", "%d"),
    "DDMMYYYY": ("%d", "%m", "%Y"),
    "DDMMYY": ("%d", "%m", "%y"),
    "YEAR": ("%Y",),
}
_TIME_FORMAT = "%H%M%S"
_DEFAULT_SUBOPTION = "YYYYMMDD"


def _formattime_format(suboption: str, date_separator: str) -> str:
    """DATESEP separates date parts only — TIME is governed by TIMESEP."""
    if suboption == "TIME":
        return _TIME_FORMAT
    parts = _DATE_PARTS.get(suboption)
    if parts is None:
        logger.warning(
            "FORMATTIME %s is not implemented — formatting as %s",
            suboption,
            _DEFAULT_SUBOPTION,
        )
        parts = _DATE_PARTS[_DEFAULT_SUBOPTION]
    return date_separator.join(parts)


def make_formattime_builtin() -> object:
    """Return a builtin that formats the current time per a FORMATTIME sub-option.

    Called once per output sub-option with args (sub-option, date_separator).
    """

    def __cics_formattime(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        from datetime import datetime, timezone

        suboption = str(args[0].value).strip().upper() if args else _DEFAULT_SUBOPTION
        separator = str(args[1].value) if len(args) > 1 else ""
        return BuiltinResult(
            value=datetime.now(timezone.utc).strftime(
                _formattime_format(suboption, separator)
            )
        )

    return __cics_formattime


def make_writeq_td_builtin(queue: list[str]) -> object:
    def __cics_writeq_td(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        data = str(args[0].value) if args else ""
        name = str(args[1].value) if len(args) > 1 else "CSMT"
        queue.append(f"[{name}] {data}")
        return BuiltinResult(value=_RESP_NORMAL)

    return __cics_writeq_td


def make_handle_abend_builtin() -> object:
    def __cics_handle_abend(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        logger.info("HANDLE ABEND — no-op in emulation")
        return BuiltinResult(value=None)

    return __cics_handle_abend


def make_runtime_noop_builtin(verb: str, reason: str) -> object:
    """A verb with nothing to do in this runtime, as opposed to one not yet
    implemented.

    The distinction is the point: an unimplemented verb abends
    (__cics_abend_unsupported) because a program depending on it would
    otherwise run on as though it had executed. A verb registered here has been
    judged to have no work in this emulation, and ``reason`` records that
    judgement at the registration site so it cannot decay into silence.
    """

    def __cics_runtime_noop(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        logger.debug("%s is a no-op in this runtime: %s", verb, reason)
        return BuiltinResult(value=0)

    return __cics_runtime_noop


def make_handle_noop_builtin(verb: str) -> object:
    """Explicit no-op for HANDLE CONDITION / HANDLE AID.

    Deferred to the HANDLE runtime-dispatch machinery follow-up
    (docs/superpowers/plans/2026-06-07-cics-handle-condition-machinery.md). The
    registration args (condition/AID -> label pairs) are intentionally ignored;
    we log so the deferral is visible rather than silently dropped.
    """

    def __cics_handle_noop(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        logger.info("%s ignored (no-op; HANDLE machinery deferred)", verb)
        return BuiltinResult(value=None)

    return __cics_handle_noop


def make_abend_builtin(result_holder: list) -> object:  # type: ignore[type-arg]
    def __cics_abend(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        abcode = str(args[0].value) if args else "UNKN"
        result_holder[0] = DispatchResult(kind=DispatchKind.ABEND, abcode=abcode)
        return BuiltinResult(value=None)

    return __cics_abend


def make_abend_unhandled_builtin(result_holder: list) -> object:  # type: ignore[type-arg]
    """Abend for a raised condition with no handler registered.

    Real CICS assigns a distinct AEIx code per condition; that mapping is not
    reproduced here (see cics/conditions.py), so the message carries the resp
    code and the abcode is one value meaning "unhandled condition".
    """

    def __cics_abend_unhandled(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        resp = int(args[0].value) if args else 0
        logger.error(
            "unhandled CICS condition, EIBRESP=%d — abending %s",
            resp,
            UNHANDLED_ABCODE,
        )
        result_holder[0] = DispatchResult(
            kind=DispatchKind.ABEND, abcode=UNHANDLED_ABCODE
        )
        return BuiltinResult(value=resp)

    return __cics_abend_unhandled


def make_abend_unsupported_builtin(result_holder: list) -> object:  # type: ignore[type-arg]
    """Abend for an EXEC CICS verb this runtime does not implement.

    Reached only if the program actually executes the statement. Lowering
    cannot refuse the whole program: the corpus carries unimplemented verbs on
    abend and error paths that a healthy run never touches, so refusing to
    compile would block programs over code that never runs. Emitting this abend
    puts the failure where the program depended on the verb.
    """

    def __cics_abend_unsupported(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        verb = str(args[0].value).strip() if args else ""
        logger.error(
            "EXEC CICS %s is not implemented by this runtime — abending %s",
            verb,
            UNSUPPORTED_VERB_ABCODE,
        )
        result_holder[0] = DispatchResult(
            kind=DispatchKind.ABEND, abcode=UNSUPPORTED_VERB_ABCODE
        )
        return BuiltinResult(value=0)

    return __cics_abend_unsupported


def make_inquire_builtin(program_cache: dict) -> object:  # type: ignore[type-arg]
    def __cics_inquire(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        name = str(args[0].value).strip() if args else ""
        resp = _RESP_NORMAL if name in program_cache else _RESP_PGMIDERR
        return BuiltinResult(value=resp)

    return __cics_inquire
