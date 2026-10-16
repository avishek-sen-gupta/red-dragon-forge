"""What a run's optional coprocessors add to it: their builtins, the CICS unit-of-work hooks, and the rollback an abend runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from cics.transaction_hooks import TransactionHooks
from interpreter.func_name import FuncName
from interpreter.vm.builtin import Builtin


@dataclass(frozen=True)
class Coprocessing:
    on_abend: Callable[[], None]
    hooks: TransactionHooks
    builtins: Mapping[FuncName, Builtin]
