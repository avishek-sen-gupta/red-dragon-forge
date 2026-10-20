"""CICS flow control builtins — RETURN TRANSID, XCTL context setters, LINK."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from cics.builtins.screen import CicsBuiltin
from cics.builtins.system import (
    make_abend_builtin,
    make_abend_unhandled_builtin,
    make_abend_unsupported_builtin,
)
from cics.cell import Holder, held_or, hold
from cics.conditions import code_for
from cics.transaction_hooks import no_hook
from cics.types import CicsContext, DispatchKind, DispatchResult
from interpreter.address import Address
from interpreter.func_name import FuncName
from interpreter.project.entry_point import EntryPoint
from interpreter.project.program_entry import ProgramEntry
from interpreter.project.types import LinkedProgram
from interpreter.run import run_linked
from interpreter.types.typed_value import TypedValue
from interpreter.vm.builtin import Builtin
from interpreter.vm.vm_types import BuiltinResult, VMState

logger = logging.getLogger(__name__)

_TASK_END_HOOK = FuncName("__cics_task_end_hook")
_COMMAREA = Address("rgn_commarea")
_NOT_ABENDED = DispatchResult(kind=DispatchKind.RETURN)


class RunLinked(Protocol):
    """How LINK runs the program it names: run_linked, or a test's stand-in."""

    def __call__(
        self,
        linked: LinkedProgram,
        entry_point: EntryPoint | ProgramEntry,
        *,
        max_steps: int,
        builtins: Mapping[FuncName, Builtin],
        initial_vm: VMState,
    ) -> VMState: ...


def _text(args: Sequence[TypedValue], index: int) -> str:
    return str(args[index].value) if len(args) > index else ""


def _bytes(args: Sequence[TypedValue], index: int) -> bytes:
    return bytes(args[index].value) if len(args) > index else b""


def _int(args: Sequence[TypedValue], index: int) -> int:
    return int(args[index].value) if len(args) > index else 0


def _return_result(args: Sequence[TypedValue]) -> DispatchResult:
    if not args:
        return DispatchResult(kind=DispatchKind.RETURN)
    if len(args) == 1:
        return DispatchResult(kind=DispatchKind.RETURN, commarea=_bytes(args, 0))
    return DispatchResult(
        kind=DispatchKind.RETURN_TRANSID,
        transid=_text(args, 0).strip(),
        commarea=_bytes(args, 1),
    )


def make_set_return_context_builtin(
    result_holder: Holder[DispatchResult],
) -> CicsBuiltin:
    """Return __cics_set_return_context builtin.

    With no args → plain RETURN. With args[0]=transid, args[1]=commarea → RETURN_TRANSID.
    """

    def __cics_set_return_context(
        args: Sequence[TypedValue], vm: VMState
    ) -> BuiltinResult:
        hold(result_holder, _return_result(args))
        return BuiltinResult(value=None)

    return __cics_set_return_context


def make_set_xctl_context_builtin(
    result_holder: Holder[DispatchResult],
    program_cache: Mapping[str, LinkedProgram],
) -> CicsBuiltin:
    """Return __cics_set_xctl_context builtin.

    args[0]=program name, args[1]=commarea bytes.
    """

    def __cics_set_xctl_context(
        args: Sequence[TypedValue], vm: VMState
    ) -> BuiltinResult:
        program = _text(args, 0).strip()
        if program not in program_cache:
            logger.error("XCTL to unknown program %r — PGMIDERR", program)
            return BuiltinResult(value=code_for("PGMIDERR"))
        hold(
            result_holder,
            DispatchResult(
                kind=DispatchKind.XCTL,
                program=program,
                commarea=_bytes(args, 1),
            ),
        )
        return BuiltinResult(value=code_for("NORMAL"))

    return __cics_set_xctl_context


def _linked_table(
    builtins: Mapping[FuncName, Builtin],
    result_holder: Holder[DispatchResult],
) -> Mapping[FuncName, Builtin]:
    return MappingProxyType(
        {
            **builtins,
            _TASK_END_HOOK: no_hook,
            FuncName("__cics_abend"): make_abend_builtin(result_holder),
            FuncName("__cics_abend_unhandled"): make_abend_unhandled_builtin(
                result_holder
            ),
            FuncName("__cics_abend_unsupported"): make_abend_unsupported_builtin(
                result_holder
            ),
        }
    )


def _abcode_of(result_holder: Holder[DispatchResult]) -> str:
    result = held_or(result_holder, _NOT_ABENDED)
    if result.kind != DispatchKind.ABEND:
        return ""
    return str(result.abcode)


@dataclass(frozen=True)
class _Link:
    """How LINK runs its target: the runner, its step budget and the table the target runs with."""

    run: RunLinked
    max_steps: int
    builtins: Mapping[FuncName, Builtin]


def _linked_commarea(
    link: _Link,
    linked: LinkedProgram,
    name: str,
    context: CicsContext,
    commarea: bytes,
) -> bytes:
    from cics.vm_init import make_cics_initial_vm

    final_vm = link.run(
        linked,
        ProgramEntry(name),
        max_steps=link.max_steps,
        builtins=link.builtins,
        initial_vm=make_cics_initial_vm(context, commarea),
    )
    return bytes(final_vm.region_get(_COMMAREA) or b"")


def _isolated_run(
    link: _Link,
    linked: LinkedProgram,
    name: str,
    context: CicsContext,
    commarea: bytes,
    result_holder: Holder[DispatchResult],
) -> tuple[bytes, str]:
    saved = result_holder[0]
    hold(result_holder, None)
    try:
        modified = _linked_commarea(link, linked, name, context, commarea)
        return modified, _abcode_of(result_holder)
    finally:
        hold(result_holder, saved)


def _write_back(vm: VMState, modified: bytes, offset: int, length: int) -> None:
    from cics.builtins.vsam import _write_into_ws

    if length > 0:
        _write_into_ws(vm, modified[:length], offset, length)


def _link_target(args: Sequence[TypedValue]) -> str:
    return _text(args, 0).strip("' ")


def make_link_resolve_builtin(
    program_cache: Mapping[str, LinkedProgram],
) -> CicsBuiltin:
    """Return __cics_link_resolve: NORMAL when the region holds the LINK target, PGMIDERR when not."""

    def __cics_link_resolve(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        name = _link_target(args)
        if name not in program_cache:
            logger.error("LINK to unknown program %r — PGMIDERR", name)
            return BuiltinResult(value=code_for("PGMIDERR"))
        return BuiltinResult(value=code_for("NORMAL"))

    return __cics_link_resolve


def make_link_builtin(
    program_cache: Mapping[str, LinkedProgram],
    result_holder: Holder[DispatchResult],
    context_holder: Sequence[CicsContext],
    max_steps: int,
    *,
    region_builtins: Callable[[], Mapping[FuncName, Builtin]],
    _run_fn: RunLinked = run_linked,
) -> CicsBuiltin:
    """Return __cics_link builtin.

    args: (prog_name, ca_bytes, ca_offset, ca_len)

    Runs the named program synchronously with a copy of the caller's COMMAREA,
    then writes the modified COMMAREA back into the caller's WS at the given
    offset/length, and answers the program's abend code, or "" when it did not
    abend. The caller's lowering resolves the target first (__cics_link_resolve)
    and routes a reported abend to its own exit or abends the task with that
    code. The inner program's abend builtins never run on_abend: backout runs
    once, where the abend is finally left unhandled. Uses save/restore on
    result_holder so the inner program's
    EXEC CICS RETURN never affects outer transaction routing, and runs the
    inner program with the region's table (``region_builtins()``) with
    __cics_task_end_hook replaced by a no-op, so that RETURN does not fire a composed coprocessor's real task-end hook (e.g. squall's
    commit + cursor-close) mid-task — the LINKed program's RETURN ends the
    LINK, not the caller's still-open unit of work.

    __cics_syncpoint_hook and __cics_rollback_hook are deliberately NOT
    suppressed here: unlike RETURN, EXEC CICS SYNCPOINT (or SYNCPOINT
    ROLLBACK) issued by a LINKed program is a real commit/rollback point for
    the WHOLE unit of work, caller included — real CICS shares one Db2
    thread/UOW across a LINK chain, so a LINKed program's SYNCPOINT must
    reach it exactly like the caller's own would.
    """

    def __cics_link(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
        name = _link_target(args)
        modified, abcode = _isolated_run(
            _Link(_run_fn, max_steps, _linked_table(region_builtins(), result_holder)),
            program_cache[name],
            name,
            context_holder[0],
            _bytes(args, 1),
            result_holder,
        )
        _write_back(vm, modified, _int(args, 2), _int(args, 3))
        return BuiltinResult(value=abcode)

    return __cics_link
