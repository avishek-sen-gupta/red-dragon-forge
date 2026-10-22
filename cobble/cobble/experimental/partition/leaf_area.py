"""The elementary fields of one program region, ordered for range lookups."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from itertools import takewhile

from cobble.experimental.partition.field_leaf import FieldLeaf


@dataclass(frozen=True)
class LeafArea:
    """Leaves sorted by start, with the longest leaf bounding how far back an overlap can begin."""

    leaves: tuple[FieldLeaf, ...]
    starts: tuple[int, ...]
    longest: int

    def overlapping(self, start: int, end: int) -> tuple[FieldLeaf, ...]:
        candidates = takewhile(
            lambda i: self.starts[i] > start - self.longest,
            range(bisect_left(self.starts, end) - 1, -1, -1),
        )
        return tuple(
            self.leaves[i] for i in candidates if self.leaves[i].overlaps(start, end)
        )


def leaf_area(leaves: tuple[FieldLeaf, ...]) -> LeafArea:
    ranked = sorted((leaf.start, leaf.end, i) for i, leaf in enumerate(leaves))
    ordered = tuple(leaves[place[-1]] for place in ranked)
    return LeafArea(
        leaves=ordered,
        starts=tuple(leaf.start for leaf in ordered),
        longest=max(leaf.end - leaf.start for leaf in ordered),
    )
