"""One provenance row: a statement's write, one source of it, and where that source was defined."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.crossing import Crossing
from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.fields.origin import Origin
from cobble.dataflow.fields.sink import Sink


@dataclass(frozen=True)
class DepRow:
    """One dep, with extents parsed into comparable ranges. ``entry`` says the
    source's bytes may still hold what the program was entered with; ``landing`` is
    where the source's first byte landed in the target, when the bytes moved
    unchanged, and nothing otherwise; ``rebuilt`` that the write built the target's value in place (arithmetic, STRING).
    """

    program: str
    via: str
    target: ByteRange
    origin: Origin
    source: ByteRange
    site: str
    definers: tuple[str, ...]
    sink: Sink
    entry: bool = False
    crossing: Crossing = Crossing.NONE
    landing: tuple[int, ...] = ()
    rebuilt: bool = False
