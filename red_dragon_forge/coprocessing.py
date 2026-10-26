"""What a run's optional coprocessors add to it: squall's runtime, whose entries are its builtins, and the rollback an abend runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from interpreter.func_name import FuncName
from interpreter.vm.builtin import Builtin
from squall.sql_runtime import SqlRuntime


@dataclass(frozen=True)
class Coprocessing:
    on_abend: Callable[[], None]
    sql: SqlRuntime

    @property
    def builtins(self) -> Mapping[FuncName, Builtin]:
        return self.sql.entries
