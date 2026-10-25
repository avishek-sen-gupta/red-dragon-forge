"""A read's bytes and the definers that may have filled them, remembered by those two alone, with the sites already followed to reach it."""

from __future__ import annotations

from dataclasses import dataclass, field

from cobble.dataflow.fields.extent_text import ByteRange


@dataclass(frozen=True)
class FillQuery:
    extent: ByteRange
    definers: tuple[str, ...]
    excluded: frozenset[str] = field(compare=False)
