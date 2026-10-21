"""CICS system service builtins — curried closures over shared state."""

from __future__ import annotations

import logging
import struct
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta

from cics.builtins.cells import FieldWrite, commit_region, write_fields
from cics.builtins.screen import CicsBuiltin, ws_region
from cics.cell import Holder, hold
from cics.conditions import UNHANDLED_ABCODE, UNSUPPORTED_VERB_ABCODE
from cics.dat_form import DatForm
from cics.types import CicsContext, DispatchKind, DispatchResult
from interpreter.address import NO_ADDRESS, Address
from interpreter.cobol.layout_data import field_positions
from interpreter.encoding.ebcdic_table import EbcdicTable
from interpreter.project.types import LinkedProgram
from interpreter.types.typed_value import TypedValue
from interpreter.var_name import VarName
from interpreter.vm.vm_types import BuiltinResult, VMState

logger = logging.getLogger(__name__)

_RESP_NORMAL = 0  # DFHRESP(NORMAL) — nothing went wrong
_RESP_PGMIDERR = 27  # DFHRESP(PGMIDERR) — INQUIRE's "program not found"


_WS_REGION = VarName("__ws_region")


def _ascii_to_ebcdic_bytes(s: str, length: int) -> bytes:
    padded = s.ljust(length)[:length]
    return bytes(
        EbcdicTable.ASCII_TO_EBCDIC[ord(c)] if ord(c) < 256 else 0x40 for c in padded
    )


def _get_ws_region_addr(vm: VMState) -> Address:
    return next(
        (
            Address(str(frame.local_vars[_WS_REGION].value))
            for frame in reversed(vm.call_stack)
            if _WS_REGION in frame.local_vars
        ),
        NO_ADDRESS,
    )


def _eib_writes(ctx: CicsContext) -> tuple[FieldWrite, ...]:
    aid_byte = ord(ctx.eibaid) if ctx.eibaid else 0x7D
    return (
        FieldWrite("EIBTRNID", _ascii_to_ebcdic_bytes(ctx.transid, 4)),
        FieldWrite("EIBTRMID", _ascii_to_ebcdic_bytes(ctx.termid, 4)),
        FieldWrite("EIBCALEN", struct.pack(">h", len(ctx.commarea))),
        FieldWrite("EIBAID", bytes((aid_byte,))),
        FieldWrite("EIBRESP", struct.pack(">i", 0)),
        FieldWrite("EIBRESP2", struct.pack(">i", 0)),
    )


def make_init_eib_builtin(context_holder: Sequence[CicsContext]) -> CicsBuiltin:
    """Return a builtin that writes EIB fields to WS at procedure entry."""

    def __cics_init_eib(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        region = ws_region(vm)
        if not region.data:
            logger.warning("__cics_init_eib: no WS region in VM — EIB not initialised")
            return BuiltinResult(value=None)
        write_fields(
            field_positions(vm.declarations),
            region.data,
            _eib_writes(context_holder[0]),
        )
        commit_region(vm, region.address, region.data)
        return BuiltinResult(value=None)

    return __cics_init_eib


ASSIGN_SUBOPTIONS = ("APPLID", "SYSID", "USERID")

# The userid CICS reports for a task that has not signed on.
DEFAULT_USERID = "CICSUSER"


def make_assign_builtin(
    applid: str = "CARDDEMO", sysid: str = "SYS1", userid: str = DEFAULT_USERID
) -> CicsBuiltin:
    """Return a builtin that yields the value of an ASSIGN output sub-option.

    Called once per sub-option in ``ASSIGN_SUBOPTIONS`` with the key in
    ``args[0]``; returns the configured value so the caller can copy it back into
    the named field. Anything else yields an empty string.
    """

    values: Mapping[str, str] = dict(
        zip(ASSIGN_SUBOPTIONS, (applid, sysid, userid), strict=True)
    )

    def __cics_assign(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        key = str(args[0].value).strip().upper() if args else ""
        if key and key not in values:
            logger.warning(
                "ASSIGN %s is not implemented — yielding an empty value", key
            )
        return BuiltinResult(value=values.get(key, ""))

    return __cics_assign


_ABSTIME_EPOCH = datetime(1900, 1, 1)
_MILLISECOND = timedelta(milliseconds=1)


def make_asktime_builtin(now: Callable[[], datetime]) -> CicsBuiltin:
    """ASKTIME: milliseconds since 00:00 on 1 January 1900, in the region's local time."""

    def __cics_asktime(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        local = now().replace(tzinfo=None)
        return BuiltinResult(value=(local - _ABSTIME_EPOCH) // _MILLISECOND)

    return __cics_asktime


def make_datform_builtin(datform: DatForm) -> CicsBuiltin:
    """The region's DATFORM, which orders a FORMATTIME DATE."""

    def __cics_datform(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        return BuiltinResult(value=datform.value)

    return __cics_datform


def make_writeq_td_builtin(write_line: Callable[[str], None]) -> CicsBuiltin:
    def __cics_writeq_td(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        data = str(args[0].value) if args else ""
        name = str(args[1].value) if len(args) > 1 else "CSMT"
        write_line(f"[{name}] {data}")
        return BuiltinResult(value=_RESP_NORMAL)

    return __cics_writeq_td


def make_handle_abend_builtin() -> CicsBuiltin:
    def __cics_handle_abend(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        logger.info("HANDLE ABEND — no-op in emulation")
        return BuiltinResult(value=None)

    return __cics_handle_abend


def make_runtime_noop_builtin(verb: str, reason: str) -> CicsBuiltin:
    """A verb with nothing to do in this runtime, as opposed to one not yet
    implemented.

    The distinction is the point: an unimplemented verb abends
    (__cics_abend_unsupported) because a program depending on it would
    otherwise run on as though it had executed. A verb registered here has been
    judged to have no work in this emulation, and ``reason`` records that
    judgement at the registration site so it cannot decay into silence.
    """

    def __cics_runtime_noop(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        logger.debug("%s is a no-op in this runtime: %s", verb, reason)
        return BuiltinResult(value=0)

    return __cics_runtime_noop


def _no_rollback() -> None:
    """Default on_abend: no composed SQL runtime supplied a rollback
    callable, so there is nothing to roll back."""


def _run_on_abend(on_abend: Callable[[], None]) -> None:
    """Run the composed rollback callable without letting it destroy the
    abend it is rolling back for.

    The caller sets ``result_holder[0]`` to the ABEND DispatchResult BEFORE
    calling this, and this never lets an exception from ``on_abend`` escape:
    a raising rollback (a dropped Db2 connection, say) must not turn a clean
    abend into a Python crash the driver has to propagate instead of
    painting on screen -- the exact shape forge-6jj already fixed once on
    this branch (an unknown-program XCTL abended internally but crashed the
    driver), reintroduced here if this call is allowed to raise.
    """
    # on_abend is an arbitrary composed callable (Task 10 wires a live Db2
    # rollback here); any failure in it must not out-run the abend it was
    # trying to clean up after, so the catch is deliberately blind.
    try:
        on_abend()
    except Exception:
        logger.exception("on_abend callable raised; the abend still stands")


def make_abend_builtin(
    result_holder: Holder[DispatchResult],
    on_abend: Callable[[], None] = _no_rollback,
) -> CicsBuiltin:
    def __cics_abend(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        abcode = str(args[0].value) if args else "UNKN"
        hold(result_holder, DispatchResult(kind=DispatchKind.ABEND, abcode=abcode))
        _run_on_abend(on_abend)
        return BuiltinResult(value=None)

    return __cics_abend


def make_abend_unhandled_builtin(
    result_holder: Holder[DispatchResult],
    on_abend: Callable[[], None] = _no_rollback,
) -> CicsBuiltin:
    """Abend for a raised condition with no handler registered.

    Real CICS assigns a distinct AEIx code per condition; that mapping is not
    reproduced here (see cics/conditions.py), so the message carries the resp
    code and the abcode is one value meaning "unhandled condition".
    """

    def __cics_abend_unhandled(
        args: Sequence[TypedValue], vm: VMState
    ) -> BuiltinResult:
        resp = int(args[0].value) if args else 0
        logger.error(
            "unhandled CICS condition, EIBRESP=%d — abending %s",
            resp,
            UNHANDLED_ABCODE,
        )
        hold(
            result_holder,
            DispatchResult(kind=DispatchKind.ABEND, abcode=UNHANDLED_ABCODE),
        )
        _run_on_abend(on_abend)
        return BuiltinResult(value=resp)

    return __cics_abend_unhandled


def make_abend_unsupported_builtin(
    result_holder: Holder[DispatchResult],
    on_abend: Callable[[], None] = _no_rollback,
) -> CicsBuiltin:
    """Abend for an EXEC CICS verb this runtime does not implement.

    Reached only if the program actually executes the statement. Lowering
    cannot refuse the whole program: the corpus carries unimplemented verbs on
    abend and error paths that a healthy run never touches, so refusing to
    compile would block programs over code that never runs. Emitting this abend
    puts the failure where the program depended on the verb.
    """

    def __cics_abend_unsupported(
        args: Sequence[TypedValue], vm: VMState
    ) -> BuiltinResult:
        verb = str(args[0].value).strip() if args else ""
        logger.error(
            "EXEC CICS %s is not implemented by this runtime — abending %s",
            verb,
            UNSUPPORTED_VERB_ABCODE,
        )
        hold(
            result_holder,
            DispatchResult(kind=DispatchKind.ABEND, abcode=UNSUPPORTED_VERB_ABCODE),
        )
        _run_on_abend(on_abend)
        return BuiltinResult(value=0)

    return __cics_abend_unsupported


def make_inquire_builtin(program_cache: Mapping[str, LinkedProgram]) -> CicsBuiltin:
    def __cics_inquire(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        name = str(args[0].value).strip() if args else ""
        resp = _RESP_NORMAL if name in program_cache else _RESP_PGMIDERR
        return BuiltinResult(value=resp)

    return __cics_inquire


def _digits(raw: bytes | bytearray | str) -> str:
    if isinstance(raw, (bytes, bytearray)):
        return "".join(str(b & 0x0F) for b in raw if 0xF0 <= b <= 0xF9)
    return "".join(c for c in raw if c.isdigit())


def make_bif_deedit_builtin() -> CicsBuiltin:
    """EXEC CICS BIF DEEDIT — strip non-digit characters from a field in-place.

    Receives the raw field bytes (EBCDIC) and the declared length. Returns a
    Python str of digit characters (ASCII '0'-'9'), left-justified and
    right-padded with '0' to ``length`` characters. The caller writes this back
    into the field via ``emit_copy_back_str``, which re-encodes to EBCDIC.

    EBCDIC digit bytes are 0xF0-0xF9; any other byte is treated as a
    non-digit editing character and discarded.
    """

    def __cics_bif_deedit(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        raw = args[0].value if args else b""
        length = int(args[1].value) if len(args) > 1 else len(raw)
        return BuiltinResult(value=_digits(raw)[:length].ljust(length, "0"))

    return __cics_bif_deedit
