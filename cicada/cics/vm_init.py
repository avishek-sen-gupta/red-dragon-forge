"""VM initialisation helpers shared by the dispatcher and LINK builtin."""

from __future__ import annotations

from dataclasses import replace

from cics.types import CicsContext
from interpreter.address import Address
from interpreter.cobol.call_arguments import call_arguments
from interpreter.cobol.program_object import ARGUMENTS_PARAM
from interpreter.func_name import FuncName
from interpreter.types.type_expr import UNKNOWN
from interpreter.types.typed_value import typed
from interpreter.var_name import VarName
from interpreter.vm.vm_types import StackFrame, VMState


def make_cics_initial_vm(context: CicsContext, ca_bytes: bytes) -> VMState:
    """Build a fresh VMState with rgn_commarea and standard CICS locals.

    The COMMAREA is argument 0 of the entry parameter, so it binds the
    program's first LINKAGE 01 -- DFHCOMMAREA.
    """
    vm = VMState()
    commarea_addr = Address("rgn_commarea")
    vm.region_set(commarea_addr, bytearray(ca_bytes))
    arguments = call_arguments(vm, [commarea_addr])
    return replace(
        vm,
        call_stack=[
            StackFrame(
                function_name=FuncName("main"),
                local_vars={
                    VarName("__cics_transid"): typed(context.transid, UNKNOWN),
                    VarName("__cics_eibcalen"): typed(len(ca_bytes), UNKNOWN),
                    VarName("__cics_eibaid"): typed(context.eibaid, UNKNOWN),
                    ARGUMENTS_PARAM: arguments,
                },
            )
        ],
    )
