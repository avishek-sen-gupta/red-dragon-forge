"""What installing the SQL runtime yields: the ``__exec_sql`` entry and the three unit-of-work hooks a composer wires in."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from interpreter.func_name import FuncName
from interpreter.vm.builtin import Builtin


@dataclass(frozen=True)
class SqlRuntime:
    entries: Mapping[FuncName, Builtin]
    reset_session: Builtin
    syncpoint: Builtin
    rollback: Builtin
