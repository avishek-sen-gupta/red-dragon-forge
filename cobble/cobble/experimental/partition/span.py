"""One end of a move: its byte range and the elementary fields that hold those bytes."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.extent_text import ByteRange
from cobble.experimental.partition.field_leaf import FieldLeaf


@dataclass(frozen=True)
class Span:
    """A byte range and the fields it resolves to."""

    range: ByteRange
    fields: tuple[FieldLeaf, ...]
