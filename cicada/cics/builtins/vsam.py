"""CICS VSAM point-operation builtins — curried closures over a VsamEngine.

These are value-in/value-out builtins with one documented exception: ``__cics_read``
fills the program's INTO buffer itself (locked design "Option A"). On a successful
read it writes the record into the WORKING-STORAGE region at the INTO field's
compile-time offset and RETURNS only the response code; the lowering then writes
that resp into EIBRESP/RESP via ``emit_resp_writeback``.

NOTE: the INTO field is assumed to live in WORKING-STORAGE — true for the target
programs. ``_get_ws_region_addr`` locates that region by walking the call stack.

Browse operations (STARTBR/READNEXT/READPREV/ENDBR) reuse the same Option-A
buffer fill: READNEXT/READPREV write the record into the INTO field and return
the resp code. This is single-task emulation, so every browse op on a file uses
a fixed implicit cursor key ``(_TASK_ID, file_name, "0")``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from cics.builtins.cells import commit_region, write_at
from cics.builtins.screen import CicsBuiltin
from cics.builtins.system import _get_ws_region_addr
from cics.vsam.engine import VsamEngine
from cics.vsam.key_match import KeyMatch
from cics.vsam.read_outcome import ReadOutcome
from cics.vsam.record_read import RecordRead
from interpreter.address import Address
from interpreter.types.typed_value import TypedValue
from interpreter.vm.vm_types import BuiltinResult, VMState

logger = logging.getLogger(__name__)

# Single-task emulation: one implicit cursor per file (see module docstring).
_TASK_ID = "cics_task"


def _write_into_ws(vm: VMState, record: bytes, offset: int, length: int) -> None:
    """Write ``record`` into the WORKING-STORAGE region at the INTO field's offset.

    Pads/truncates the record to ``length`` bytes. No-op (with a warning) if the
    region is missing.
    """
    address = _get_ws_region_addr(vm)
    if not address.is_present():
        logger.warning("VSAM read: no __ws_region in VM — INTO not filled")
        return
    _write_into_region(vm, address, record[:length].ljust(length, b"\x00"), offset)


def _write_into_region(
    vm: VMState, address: Address, payload: bytes, offset: int
) -> None:
    match vm.region_get(address):
        case bytearray() as region:
            write_at(region, offset, payload)
            commit_region(vm, address, region)
        case _:
            logger.warning("VSAM read: WS region not allocated — INTO not filled")


def _filled(vm: VMState, outcome: ReadOutcome, offset: int, length: int) -> int:
    match outcome:
        case RecordRead(record=record):
            _write_into_ws(vm, record, offset, length)
    return outcome.resp


def _file(args: Sequence[TypedValue], i: int = 0) -> str:
    return str(args[i].value).strip("'\" ") if len(args) > i else ""


def _bytes(args: Sequence[TypedValue], i: int) -> bytes:
    v = args[i].value if len(args) > i else b""
    return (
        bytes(v)
        if isinstance(v, (bytes, bytearray, list))
        else str(v).encode("cp037", "replace")
    )


def _int(args: Sequence[TypedValue], i: int) -> int:
    return int(args[i].value) if len(args) > i else 0


def _key_match(args: Sequence[TypedValue], i: int) -> KeyMatch:
    return KeyMatch[str(args[i].value).strip()]


def make_vsam_read_builtin(engine: VsamEngine) -> CicsBuiltin:
    """READ: returns the resp code; on success writes the record into INTO buffer.

    args: (file_str, key_bytes, key_match_name, into_offset_int, into_length_int)
    """

    def __cics_read(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        outcome = engine.read(_file(args, 0), _bytes(args, 1), _key_match(args, 2))
        return BuiltinResult(value=_filled(vm, outcome, _int(args, 3), _int(args, 4)))

    return __cics_read


def make_vsam_write_builtin(engine: VsamEngine) -> CicsBuiltin:
    """WRITE: args (file, key_bytes, key_len, record_bytes); returns resp."""

    def __cics_write(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        return BuiltinResult(
            value=engine.write(
                _file(args, 0), _bytes(args, 1), _int(args, 2), _bytes(args, 3)
            )
        )

    return __cics_write


def make_vsam_rewrite_builtin(engine: VsamEngine) -> CicsBuiltin:
    """REWRITE: args (file, key_bytes, key_len, record_bytes); returns resp."""

    def __cics_rewrite(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        return BuiltinResult(
            value=engine.rewrite(
                _file(args, 0), _bytes(args, 1), _int(args, 2), _bytes(args, 3)
            )
        )

    return __cics_rewrite


def make_vsam_delete_builtin(engine: VsamEngine) -> CicsBuiltin:
    """DELETE: args (file, key_bytes); an empty key deletes the record last read. Returns resp."""

    def __cics_delete(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        return BuiltinResult(value=engine.delete(_file(args, 0), _bytes(args, 1)))

    return __cics_delete


def make_vsam_key_length_builtin(engine: VsamEngine) -> CicsBuiltin:
    """The file's declared key length: args (file,); 0 for a file the table does not define."""

    def __cics_key_length(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        return BuiltinResult(value=engine.key_length(_file(args, 0)))

    return __cics_key_length


def make_vsam_startbr_builtin(engine: VsamEngine) -> CicsBuiltin:
    """STARTBR: args (file, key_bytes, key_match_name); returns resp.

    Positions the file's implicit cursor on the first record the key matches.
    """

    def __cics_startbr(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        fname = _file(args, 0)
        resp = engine.startbr(
            fname, _bytes(args, 1), (_TASK_ID, fname, "0"), start=_key_match(args, 2)
        )
        return BuiltinResult(value=resp)

    return __cics_startbr


def make_vsam_resetbr_builtin(engine: VsamEngine) -> CicsBuiltin:
    """RESETBR: args (file, key_bytes, key_match_name); returns resp.

    Repositions the file's open browse; INVREQ when there is none.
    """

    def __cics_resetbr(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        fname = _file(args, 0)
        resp = engine.resetbr(
            fname, _bytes(args, 1), (_TASK_ID, fname, "0"), start=_key_match(args, 2)
        )
        return BuiltinResult(value=resp)

    return __cics_resetbr


def make_vsam_readnext_builtin(engine: VsamEngine) -> CicsBuiltin:
    """READNEXT: args (file, into_offset, into_length); returns resp.

    On a record, fills the INTO buffer (Option A) and advances the cursor.
    """

    def __cics_readnext(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        fname = _file(args, 0)
        into_off, into_len = _int(args, 1), _int(args, 2)
        outcome = engine.readnext(fname, (_TASK_ID, fname, "0"))
        return BuiltinResult(value=_filled(vm, outcome, into_off, into_len))

    return __cics_readnext


def make_vsam_readprev_builtin(engine: VsamEngine) -> CicsBuiltin:
    """READPREV: args (file, into_offset, into_length); returns resp.

    On a record, fills the INTO buffer (Option A) and moves the cursor back.
    """

    def __cics_readprev(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        fname = _file(args, 0)
        into_off, into_len = _int(args, 1), _int(args, 2)
        outcome = engine.readprev(fname, (_TASK_ID, fname, "0"))
        return BuiltinResult(value=_filled(vm, outcome, into_off, into_len))

    return __cics_readprev


def make_vsam_endbr_builtin(engine: VsamEngine) -> CicsBuiltin:
    """ENDBR: args (file,); releases the implicit cursor. Returns resp."""

    def __cics_endbr(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        fname = _file(args, 0)
        return BuiltinResult(value=engine.endbr(fname, (_TASK_ID, fname, "0")))

    return __cics_endbr
