"""What installing the CICS runtime yields: cicada's entries, the region's whole builtins table, and the START queue."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cics.interval import StartQueue
from interpreter.func_name import FuncName
from interpreter.vm.builtin import Builtin


@dataclass(frozen=True)
class CicsRuntime:
    entries: Mapping[FuncName, Builtin]
    builtins: Mapping[FuncName, Builtin]
    start_queue: StartQueue
