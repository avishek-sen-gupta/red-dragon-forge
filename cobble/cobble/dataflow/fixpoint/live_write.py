"""One write as liveness needs it: its target, whether it may leave the bytes as they were, and the storage it reads."""

from __future__ import annotations

from dataclasses import dataclass

from cobol_memory.field_extent import FieldExtent


@dataclass(frozen=True)
class LiveWrite:
    """No values and no writer node ids: liveness asks only which bytes a write
    covers and which bytes it reads, so this is all a prepared program keeps."""

    target: FieldExtent
    weak: bool
    sources: tuple[FieldExtent, ...]
    copy_start: tuple[int, ...] = ()
