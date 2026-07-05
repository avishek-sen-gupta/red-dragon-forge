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

    The COMMAREA is bound to the LINKAGE SECTION (DFHCOMMAREA) via
    __params_region. Stored as the region name string (not an Address object)
    so region writes from LINKAGE section items resolve without double-wrapping.
    """
    from interpreter.vm.vm_types import VMState, StackFrame  # noqa: PLC0415
    from interpreter.address import Address  # noqa: PLC0415

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
                VarName("__params_region"): typed(commarea_addr.value, UNKNOWN),
            },
        )
    )
    return vm


def make_entry_point(program: Any) -> Any:
    """Select the right EntryPoint predicate for a LinkedProgram.

    Uses entry_func_label when present (multi-module link); otherwise falls
    back to the bare func_* prefix predicate.
    """
    from interpreter.run import EntryPoint  # noqa: PLC0415

    entry_label = getattr(program, "entry_func_label", None)
    if entry_label is not None:
        entry_label_str = str(entry_label)
        return EntryPoint.function(
            lambda ref, _lbl=entry_label_str: str(ref.label) == _lbl
        )
    return EntryPoint.function(
        lambda ref: str(ref.label).startswith("func_")
        and not str(ref.label).startswith("func_init_params_")
    )
