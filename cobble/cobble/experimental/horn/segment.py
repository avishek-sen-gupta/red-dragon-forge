"""A run of tracked bytes in one storage region, held in the state as one bit-vector."""

from __future__ import annotations

from dataclasses import dataclass

import z3
from cobble.experimental.horn.terms import extract
from cobol_memory.field_extent import FieldExtent
from cobol_memory.region_id import RegionId


@dataclass(frozen=True)
class Segment:
    """Bytes ``start`` to ``end`` of ``region``; byte ``start`` is the most
    significant byte of the bit-vector, as the bytes read left to right."""

    region: RegionId
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start

    def holds(self, extent: FieldExtent) -> bool:
        return (
            extent.region is self.region
            and self.start <= extent.start
            and extent.end <= self.end
        )

    def overlaps(self, extent: FieldExtent) -> bool:
        return (
            extent.region is self.region
            and extent.start < self.end
            and self.start < extent.end
        )

    def bytes_of(self, extent: FieldExtent, value: z3.BitVecRef) -> z3.BitVecRef:
        return self.slice(extent.start, extent.end, value)

    def slice(self, start: int, end: int, value: z3.BitVecRef) -> z3.BitVecRef:
        return extract(8 * (self.end - start) - 1, 8 * (self.end - end), value)
