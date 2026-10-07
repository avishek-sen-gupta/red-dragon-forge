"""Which byte ranges are live on entry to each node, as merged spans per region."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import reduce
from itertools import groupby
from operator import itemgetter
from types import MappingProxyType

from cobol_memory.field_extent import FieldExtent
from cobol_memory.region_id import RegionId

Spans = Mapping[RegionId, tuple[int, ...]]

_NO_SPANS: Spans = MappingProxyType({})


@dataclass(frozen=True)
class Live:
    """Live spans per node; ``everything`` keeps every extent at every node."""

    entry: Mapping[str, Spans] = MappingProxyType({})
    everything: bool = False

    def keeps(self, node: str, extent: FieldExtent) -> bool:
        return self.everything or _overlaps(
            self.entry.get(node, _NO_SPANS).get(extent.region, ()), extent
        )


EVERYTHING = Live(everything=True)


def _overlaps(bounds: tuple[int, ...], extent: FieldExtent) -> bool:
    if extent.length <= 0:
        return False
    position = bisect_right(bounds, extent.start)
    return position % 2 == 1 or (
        position < len(bounds) and bounds[position] < extent.end
    )


def _merged(
    spans: tuple[tuple[int, int], ...], span: tuple[int, int]
) -> tuple[tuple[int, int], ...]:
    if spans and span[0] <= spans[-1][1]:
        return (*spans[:-1], (spans[-1][0], max(spans[-1][1], span[1])))
    return (*spans, span)


def spans_of(extents: Iterable[FieldExtent]) -> Spans:
    ordered = sorted(
        (extent.region.value, extent.start, extent.end, extent.region)
        for extent in extents
        if extent.length > 0
    )
    return MappingProxyType(
        {
            region: tuple(
                bound
                for span in reduce(
                    _merged, ((start, end) for _order, start, end, _region in group), ()
                )
                for bound in span
            )
            for region, group in (
                (rows[0][3], rows)
                for _, grouped in groupby(ordered, itemgetter(0))
                for rows in (tuple(grouped),)
            )
        }
    )
