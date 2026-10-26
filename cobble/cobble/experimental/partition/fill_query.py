"""A read's bytes and the definers that may have filled them: one lookup when tracing a read back."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.extent_text import ByteRange


@dataclass(frozen=True)
class FillQuery:
    extent: ByteRange
    definers: tuple[str, ...]
