"""One provenance row: a statement's write, one source of it, and where that source was defined."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.crossing import Crossing
from cobble.dataflow.fields.extent_text import ByteRange


@dataclass(frozen=True)
class DepRow:
    """One dep, with extents parsed into comparable ranges. ``entry`` says the
    source's bytes may still hold what the program was entered with."""

    program: str
    via: str
    target: ByteRange
    origin: str
    source: ByteRange
    site: str
    definers: tuple[str, ...]
    sink: str
    literal: str = ""
    entry: bool = False
    crossing: Crossing = Crossing.NONE
