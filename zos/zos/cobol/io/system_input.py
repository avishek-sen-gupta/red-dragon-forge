"""What a run's ACCEPT reads: lines served one 80-byte card per ACCEPT until they end, or nothing supplied, so an unknown value."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import partial
from typing import TypeAlias

from infrastructure.zos.access_methods.access_result import AccessCondition
from interpreter.cobol.io_provider import IOResult
from interpreter.vm.vm import Operators

SystemInput: TypeAlias = Callable[[], IOResult | Operators._Uncomputable]

_CARD = 80
_INPUT_ENDED = IOResult(AccessCondition.END_OF_FILE, None)


def unsupplied() -> Operators._Uncomputable:
    return Operators.UNCOMPUTABLE


def _next_card(lines: Iterator[str]) -> IOResult:
    return next(
        (
            IOResult(AccessCondition.OK, line.rstrip("\r\n").ljust(_CARD))
            for line in lines
        ),
        _INPUT_ENDED,
    )


def line_input(lines: Iterator[str]) -> SystemInput:
    return partial(_next_card, lines)
