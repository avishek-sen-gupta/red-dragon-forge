"""Byte ranges as merged spans per region: union, removal and overlap in sorted bounds."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Mapping
from functools import reduce
from itertools import groupby
from operator import itemgetter
from types import MappingProxyType

from cobol_memory.field_extent import FieldExtent
from cobol_memory.region_id import RegionId

Spans = Mapping[RegionId, tuple[int, ...]]

NO_SPANS: Spans = MappingProxyType({})

_END = 1 << 62

EVERY_BYTE: Spans = MappingProxyType({region: (0, _END) for region in RegionId})


def overlaps(spans: Spans, extent: FieldExtent) -> bool:
    if extent.length <= 0:
        return False
    bounds = spans.get(extent.region, ())
    position = bisect_right(bounds, extent.start)
    return position % 2 == 1 or (
        position < len(bounds) and bounds[position] < extent.start + extent.length
    )


def _merged(
    spans: tuple[tuple[int, int], ...], span: tuple[int, int]
) -> tuple[tuple[int, int], ...]:
    if spans and span[0] <= spans[-1][1]:
        return (*spans[:-1], (spans[-1][0], max(spans[-1][1], span[1])))
    return (*spans, span)


def _bounds(pairs: Iterable[tuple[int, int]]) -> tuple[int, ...]:
    return tuple(
        bound
        for pair in reduce(
            _merged, sorted(pair for pair in pairs if pair[0] < pair[1]), ()
        )
        for bound in pair
    )


def _pairs(bounds: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    return tuple(zip(bounds[::2], bounds[1::2], strict=True))


def spans_of(extents: Iterable[FieldExtent]) -> Spans:
    ordered = sorted(
        (extent.region.value, extent.start, extent.start + extent.length, extent.region)
        for extent in extents
        if extent.length > 0
    )
    return MappingProxyType(
        {
            rows[0][3]: _bounds((start, end) for _order, start, end, _region in rows)
            for _, grouped in groupby(ordered, itemgetter(0))
            for rows in (tuple(grouped),)
        }
    )


def union(left: Spans, right: Spans) -> Spans:
    if left is right or not right:
        return left
    if not left:
        return right
    return MappingProxyType(
        {
            region: _bounds(
                (*_pairs(left.get(region, ())), *_pairs(right.get(region, ())))
            )
            for region in (*left, *(region for region in right if region not in left))
        }
    )


def without(spans: Spans, extent: FieldExtent) -> Spans:
    """``spans`` less the bytes of ``extent``, or ``spans`` itself if it held none."""
    if not overlaps(spans, extent):
        return spans
    start, end = extent.start, extent.start + extent.length
    return MappingProxyType(
        {
            **spans,
            extent.region: _bounds(
                piece
                for low, high in _pairs(spans[extent.region])
                for piece in ((low, min(high, start)), (max(low, end), high))
            ),
        }
    )
