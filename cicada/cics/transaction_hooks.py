"""The unit-of-work hooks a CICS task calls at task end, SYNCPOINT and SYNCPOINT ROLLBACK; each defaults to a no-op."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from interpreter.types.typed_value import TypedValue
from interpreter.vm.builtin import Builtin
from interpreter.vm.vm_types import BuiltinResult, VMState


def no_hook(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
    return BuiltinResult(value=None)


@dataclass(frozen=True)
class TransactionHooks:
    task_end: Builtin = no_hook
    syncpoint: Builtin = no_hook
    rollback: Builtin = no_hook
