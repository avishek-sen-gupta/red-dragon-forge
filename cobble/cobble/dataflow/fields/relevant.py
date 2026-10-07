"""The bytes a restricted walk tracks, and whether a write lands on them."""

from __future__ import annotations

from dataclasses import dataclass

from cobol_memory.field_extent import FieldExtent


@dataclass(frozen=True)
class Relevant:
    """The extents a write must overlap to be kept; ``everything`` keeps every write."""

    extents: frozenset[FieldExtent] = frozenset()
    everything: bool = False

    def touches(self, target: FieldExtent) -> bool:
        return self.everything or any(_overlap(target, one) for one in self.extents)


EVERYTHING = Relevant(everything=True)


def _overlap(left: FieldExtent, right: FieldExtent) -> bool:
    return (
        left.region is right.region
        and left.start < right.end
        and right.start < left.end
    )
