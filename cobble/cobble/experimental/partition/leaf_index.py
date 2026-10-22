"""Every program's elementary fields, from the extents table, and the fields a byte range names."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter

from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.experimental.partition.extent_row import ExtentRow
from cobble.experimental.partition.field_leaf import FieldLeaf
from cobble.experimental.partition.leaf_area import LeafArea, leaf_area

_Area = tuple[str, str]


@dataclass(frozen=True)
class LeafIndex:
    """Leaves by program and region; a field is a leaf when nothing is declared under it."""

    areas: Mapping[_Area, LeafArea]

    def fields_in(self, extent: ByteRange) -> tuple[FieldLeaf, ...]:
        area = self.areas.get((extent.program, extent.region))
        hits = area.overlapping(extent.start, extent.end) if area else ()
        named = tuple(leaf for leaf in hits if extent.name in leaf.path)
        return named or hits or (_undeclared(extent),)


def _undeclared(extent: ByteRange) -> FieldLeaf:
    return FieldLeaf(
        program=extent.program,
        record="",
        name=extent.name,
        region=extent.region,
        start=extent.start,
        end=extent.end,
        pic="",
        path=(extent.name,),
    )


def _leaves_of(row: ExtentRow) -> tuple[FieldLeaf, ...]:
    return tuple(
        FieldLeaf(
            program=row.program,
            record=record,
            name=extent.name,
            region=extent.region,
            start=extent.start,
            end=extent.end,
            pic=pic,
            path=path,
        )
        for text, record, path, pic in zip(
            row.extents, row.records, row.paths, row.pics, strict=True
        )
        for extent in (byte_range(text, row.program),)
    )


def _area_of(leaf: FieldLeaf) -> _Area:
    return (leaf.program, leaf.region)


def leaf_index(rows: Iterable[ExtentRow]) -> LeafIndex:
    declared = tuple(leaf for row in rows for leaf in _leaves_of(row))
    parents = {
        (leaf.program, leaf.record, leaf.path[:depth])
        for leaf in declared
        for depth in range(1, len(leaf.path))
    }
    leaves = tuple(
        leaf
        for leaf in declared
        if (leaf.program, leaf.record, leaf.path) not in parents
    )
    ranked = sorted((_area_of(leaf), i) for i, leaf in enumerate(leaves))
    return LeafIndex(
        areas={
            area: leaf_area(tuple(leaves[i] for _, i in members))
            for area, members in groupby(ranked, itemgetter(0))
        }
    )
