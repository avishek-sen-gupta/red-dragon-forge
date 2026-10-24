"""Extents grouped by region and sorted by start, for range lookups that need not scan every one."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import groupby

from cobol_memory.field_extent import FieldExtent
from cobol_memory.region_id import RegionId

_Area = tuple[tuple[int, ...], tuple[FieldExtent, ...], int]
_NO_AREA: _Area = ((), (), 0)


@dataclass(frozen=True)
class ExtentIndex:
    """Each region's extents sorted by start, with the longest one's length bounding how far back a match can begin."""

    areas: Mapping[RegionId, _Area]

    def containing(self, read: FieldExtent) -> tuple[FieldExtent, ...]:
        starts, extents, longest = self.areas.get(read.region, _NO_AREA)
        low = bisect_left(starts, read.end - longest)
        high = bisect_right(starts, read.start)
        return tuple(extent for extent in extents[low:high] if read.end <= extent.end)

    def overlapped(self, read: FieldExtent) -> bool:
        starts, extents, longest = self.areas.get(read.region, _NO_AREA)
        low = bisect_right(starts, read.start - longest)
        high = bisect_left(starts, read.end)
        return any(
            extent.length > 0 and read.start < extent.end
            for extent in extents[low:high]
        )


def _area(extents: Iterable[FieldExtent]) -> _Area:
    ranked = sorted(
        ((extent.start, extent.length, i), extent) for i, extent in enumerate(extents)
    )
    ordered = tuple(extent for _, extent in ranked)
    return (
        tuple(extent.start for extent in ordered),
        ordered,
        max((extent.length for extent in ordered), default=0),
    )


def extent_index(extents: Iterable[FieldExtent]) -> ExtentIndex:
    ranked = sorted(
        (extent.region.value, i, extent) for i, extent in enumerate(extents)
    )
    return ExtentIndex(
        areas={
            group[0][2].region: _area(row[2] for row in group)
            for group in (
                tuple(members) for _, members in groupby(ranked, lambda row: row[0])
            )
        }
    )
