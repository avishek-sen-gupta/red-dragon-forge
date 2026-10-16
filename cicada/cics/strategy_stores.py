"""The CICS lowering strategy's writes into state it does not own.

Each store changes an object in place because its owner reads that same object
afterwards: the dialect parser's statement list is shared with every module
compile_cobol lowers, and the unsupported-verb set is the harness's cell.
"""

from __future__ import annotations

from collections.abc import MutableSequence
from typing import TypeVar

T = TypeVar("T")


def drain(items: MutableSequence[T]) -> tuple[T, ...]:
    drained = tuple(items)
    items.clear()
    return drained


def note_unsupported(verbs: set[str], verb: str) -> None:
    verbs.add(verb)
