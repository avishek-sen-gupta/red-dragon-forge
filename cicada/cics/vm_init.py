"""VM initialisation helpers shared by the dispatcher and LINK builtin."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from interpreter.func_name import FuncName
from interpreter.types.type_expr import UNKNOWN
from interpreter.types.typed_value import typed
from interpreter.var_name import VarName

if TYPE_CHECKING:
    from cics.types import CicsContext


def make_cics_initial_vm(context: "CicsContext", ca_bytes: bytes) -> Any:
    """Build a fresh VMState with rgn_commarea and standard CICS locals.

    The COMMAREA is argument 0 of the entry parameter, so it binds the
    program's first LINKAGE 01 -- DFHCOMMAREA.
    """
    from interpreter.address import Address  # noqa: PLC0415
    from interpreter.cobol.call_arguments import call_arguments  # noqa: PLC0415
    from interpreter.cobol.program_object import ARGUMENTS_PARAM  # noqa: PLC0415
    from interpreter.vm.vm_types import StackFrame, VMState  # noqa: PLC0415

    vm = VMState()
    commarea_addr = Address("rgn_commarea")
    vm.region_set(commarea_addr, bytearray(ca_bytes))
    vm.call_stack.append(
        StackFrame(
            function_name=FuncName("main"),
            local_vars={
                VarName("__cics_transid"): typed(context.transid, UNKNOWN),
                VarName("__cics_eibcalen"): typed(len(ca_bytes), UNKNOWN),
                VarName("__cics_eibaid"): typed(context.eibaid, UNKNOWN),
                ARGUMENTS_PARAM: call_arguments(vm, [commarea_addr]),
            },
        )
    )
    return vm


def make_entry_point(program: Any) -> Any:
    """Enter the program at the entry label its compile recorded."""
    from interpreter.run import EntryPoint  # noqa: PLC0415

    return EntryPoint.function(lambda ref: ref.label == program.entry_func_label)
