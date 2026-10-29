"""The pieces of tracing a read back through the copies that filled it: which writes feed a lookup, the lookup each copy asks, and how its answer splits a field."""

from __future__ import annotations

import sys
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from functools import reduce
from itertools import groupby
from operator import itemgetter

from cobble.dataflow.fields.dep_row import DepRow
from cobble.dataflow.fields.extent_text import ByteRange
from cobble.experimental.partition.field_leaf import FieldLeaf
from cobble.experimental.partition.fill_query import FillQuery
from cobble.experimental.partition.leaf_index import LeafIndex

Rows = Mapping[str, tuple[DepRow, ...]]
Fields = tuple[FieldLeaf, ...]
Feed = tuple[DepRow, FieldLeaf]


def read_of(dep: DepRow) -> FillQuery:
    return FillQuery(dep.source, dep.definers)


def written_rows(deps: Sequence[DepRow]) -> Rows:
    written = sorted(
        (dep.site, i)
        for i, dep in enumerate(deps)
        if dep.target.known and dep.sink.is_none
    )
    return {
        site: tuple(deps[i] for _, i in group)
        for site, group in groupby(written, itemgetter(0))
    }


def _joined(
    runs: tuple[tuple[int, int], ...], piece: tuple[int, int]
) -> tuple[tuple[int, int], ...]:
    if runs and piece[0] <= runs[-1][1]:
        return (*runs[:-1], (runs[-1][0], max(runs[-1][1], piece[1])))
    return (*runs, piece)


def _runs(pieces: Sequence[FieldLeaf]) -> tuple[tuple[int, int], ...]:
    return reduce(_joined, sorted((piece.start, piece.end) for piece in pieces), ())


def _covered(leaf: FieldLeaf, runs: tuple[tuple[int, int], ...]) -> bool:
    if leaf.start >= leaf.end:
        return True
    place = bisect_right(runs, (leaf.start, sys.maxsize)) - 1
    return place >= 0 and runs[place][0] <= leaf.start and leaf.end <= runs[place][1]


def _distinct(leaves: Iterable[FieldLeaf]) -> Fields:
    return tuple({leaf: None for leaf in leaves})


def _inside(row: DepRow, extent: ByteRange) -> bool:
    return (
        (row.target.program, row.target.region) == (extent.program, extent.region)
        and extent.start <= row.target.start
        and row.target.end <= extent.end
    )


def feeds(
    index: LeafIndex, rows: Rows, query: FillQuery, excluded: frozenset[str]
) -> tuple[Feed, ...]:
    return tuple(
        (row, leaf)
        for definer in query.definers
        if definer not in excluded
        for row in rows.get(definer, ())
        if _inside(row, query.extent)
        for leaf in index.fields_in(row.target)
    )


def child(row: DepRow, leaf: FieldLeaf) -> FillQuery:
    shift = row.source.start - row.target.start
    return FillQuery(
        replace(row.source, start=leaf.start + shift, end=leaf.end + shift),
        row.definers,
    )


def finer(row: DepRow, leaf: FieldLeaf, inner: Fields) -> Fields:
    if len(inner) < 2:
        return (leaf,)
    shift = row.source.start - row.target.start
    return tuple(
        replace(
            piece, region=leaf.region, start=piece.start - shift, end=piece.end - shift
        )
        for piece in inner
    )


def presented(
    index: LeafIndex, query: FillQuery, pieces: Iterable[FieldLeaf]
) -> Fields:
    found = _distinct(pieces)
    runs = _runs(found)
    kept = tuple(
        leaf for leaf in index.fields_in(query.extent) if not _covered(leaf, runs)
    )
    return _distinct((*kept, *found))
