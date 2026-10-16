"""CICS flow control builtins — RETURN TRANSID, XCTL context setters, LINK."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from cics.builtins.screen import CicsBuiltin
from cics.cell import Holder, hold
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
) -> CicsBuiltin:
    """Return __cics_set_xctl_context builtin.

    args[0]=program name, args[1]=commarea bytes.
    """

    def __cics_set_xctl_context(
        args: Sequence[TypedValue], vm: VMState
    ) -> BuiltinResult:
        hold(
            result_holder,
            DispatchResult(
                kind=DispatchKind.XCTL,
                program=_text(args, 0).strip(),
                commarea=_bytes(args, 1),
            ),
        )
        return BuiltinResult(value=None)

    return __cics_set_xctl_context


def _without_task_end(
    builtins: Mapping[FuncName, Builtin],
) -> Mapping[FuncName, Builtin]:
    return MappingProxyType({**builtins, _TASK_END_HOOK: no_hook})


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


def _isolated_commarea(
    link: _Link,
    linked: LinkedProgram,
    name: str,
    context: CicsContext,
    commarea: bytes,
    result_holder: Holder[DispatchResult],
) -> bytes:
    saved = result_holder[0]
    hold(result_holder, None)
    try:
        return _linked_commarea(link, linked, name, context, commarea)
    finally:
        hold(result_holder, saved)


def _write_back(vm: VMState, modified: bytes, offset: int, length: int) -> None:
    from cics.builtins.vsam import _write_into_ws

    if length > 0:
        _write_into_ws(vm, modified[:length], offset, length)


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
    offset/length. Uses save/restore on result_holder so the inner program's
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
        name = _text(args, 0).strip("' ")
        if name not in program_cache:
            logger.warning("EXEC CICS LINK to unknown program %r — no-op", name)
            return BuiltinResult(value=0)
        modified = _isolated_commarea(
            _Link(_run_fn, max_steps, _without_task_end(region_builtins())),
            program_cache[name],
            name,
            context_holder[0],
            _bytes(args, 1),
            result_holder,
        )
        _write_back(vm, modified, _int(args, 2), _int(args, 3))
        return BuiltinResult(value=0)

    return __cics_link
