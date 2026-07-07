"""CICS flow control builtins — RETURN TRANSID, XCTL context setters, LINK."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cics.types import DispatchKind, DispatchResult
from interpreter.types.typed_value import TypedValue
from interpreter.vm.vm_types import BuiltinResult, VMState

if TYPE_CHECKING:
    from cics.types import CicsContext

logger = logging.getLogger(__name__)


def make_noop_task_end_hook_builtin() -> object:
    """Return the default __cics_task_end_hook builtin: does nothing.

    Cicada always emits a call to this name at task end (EXEC CICS RETURN,
    with or without TRANSID) — it has no idea what, if anything, is
    registered under it. Another coprocessor composed alongside cicada may
    register its own real implementation over this default (see
    CicsLoweringStrategy.__init__'s _register_default).
    """

    def __cics_task_end_hook(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        return BuiltinResult(value=None)

    return __cics_task_end_hook


def make_set_return_context_builtin(result_holder: list) -> object:
    """Return __cics_set_return_context builtin.

    With no args → plain RETURN. With args[0]=transid, args[1]=commarea → RETURN_TRANSID.
    """

    def __cics_set_return_context(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        if not args:
            result_holder[0] = DispatchResult(kind=DispatchKind.RETURN)
        else:
            transid = str(args[0].value).strip()
            commarea = bytes(args[1].value) if len(args) > 1 else b""
            result_holder[0] = DispatchResult(
                kind=DispatchKind.RETURN_TRANSID,
                transid=transid,
                commarea=commarea,
            )
        return BuiltinResult(value=None)

    return __cics_set_return_context


def make_set_xctl_context_builtin(result_holder: list) -> object:
    """Return __cics_set_xctl_context builtin.

    args[0]=program name, args[1]=commarea bytes.
    """

    def __cics_set_xctl_context(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        program = str(args[0].value).strip() if args else ""
        commarea = bytes(args[1].value) if len(args) > 1 else b""
        result_holder[0] = DispatchResult(
            kind=DispatchKind.XCTL,
            program=program,
            commarea=commarea,
        )
        return BuiltinResult(value=None)

    return __cics_set_xctl_context


def make_link_builtin(
    program_cache: dict,
    result_holder: list,
    context_holder: "list[CicsContext]",
    max_steps: int,
    *,
    _run_fn=None,
) -> object:
    """Return __cics_link builtin.

    args: (prog_name, ca_bytes, ca_offset, ca_len)

    Runs the named program synchronously with a copy of the caller's COMMAREA,
    then writes the modified COMMAREA back into the caller's WS at the given
    offset/length. Uses save/restore on result_holder so the inner program's
    EXEC CICS RETURN never affects outer transaction routing.
    """

    def __cics_link(args: list[TypedValue], vm: VMState) -> BuiltinResult:
        from interpreter.address import Address  # noqa: PLC0415
        from cics.vm_init import make_cics_initial_vm, make_entry_point  # noqa: PLC0415
        from cics.builtins.vsam import _write_into_ws  # noqa: PLC0415

        if _run_fn is None:
            from interpreter.run import run_linked  # noqa: PLC0415

            _run = run_linked
        else:
            _run = _run_fn

        prog_name = str(args[0].value).strip("' ") if args else ""
        ca_bytes = bytes(args[1].value) if len(args) > 1 else b""
        ca_offset = int(args[2].value) if len(args) > 2 else 0
        ca_len = int(args[3].value) if len(args) > 3 else 0

        linked = program_cache.get(prog_name)
        if linked is None:
            logger.warning("EXEC CICS LINK to unknown program %r — no-op", prog_name)
            return BuiltinResult(value=0)

        # Save outer result so the inner program's RETURN does not clobber
        # the outer transaction's routing (they share result_holder).
        saved = result_holder[0]
        result_holder[0] = None
        try:
            inner_vm = make_cics_initial_vm(context_holder[0], ca_bytes)
            inner_vm.data_layout = linked.data_layout
            final_vm = _run(
                linked,
                make_entry_point(linked),
                max_steps=max_steps,
                initial_vm=inner_vm,
            )
            ca_addr = Address("rgn_commarea")
            modified = bytes(final_vm.region_get(ca_addr) or b"")
        finally:
            result_holder[0] = saved

        if ca_len > 0:
            _write_into_ws(vm, modified[:ca_len], ca_offset, ca_len)
        return BuiltinResult(value=0)

    return __cics_link
