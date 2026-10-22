"""Places every node: each cluster a ring, rings packed in rows, terminals beside their fields."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce

from cobble.experimental.partition.cluster_set import ClusterSet
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.node_kind import NodeKind

GAP = 2.0

_Point = tuple[float, float]


@dataclass(frozen=True)
class _Cursor:
    """Where the next ring goes, and the centres placed so far."""

    x: float = 0.0
    y: float = 0.0
    row_height: float = 0.0
    centres: tuple[_Point, ...] = ()


def _radius(size: int) -> float:
    return size / (2 * math.pi) if size > 1 else 0.0


def _placed(row_width: float, cursor: _Cursor, width: float) -> _Cursor:
    wraps = cursor.x > 0 and cursor.x + width > row_width
    x, y, height = (
        (0.0, cursor.y + cursor.row_height, 0.0)
        if wraps
        else (
            cursor.x,
            cursor.y,
            cursor.row_height,
        )
    )
    return _Cursor(
        x=x + width,
        y=y,
        row_height=max(height, width),
        centres=(*cursor.centres, (x + width / 2, y + width / 2)),
    )


def _ring(members: Sequence[str], centre: _Point) -> dict[str, _Point]:
    radius = _radius(len(members))
    return {
        member: (
            centre[0] + radius * math.cos(2 * math.pi * i / len(members)),
            centre[1] + radius * math.sin(2 * math.pi * i / len(members)),
        )
        for i, member in enumerate(members)
    }


def _beside(points: Sequence[_Point]) -> _Point:
    if not points:
        return (0.0, -GAP)
    return (
        sum(x for x, _ in points) / len(points) + GAP / 4,
        sum(y for _, y in points) / len(points) + GAP / 4,
    )


def _terminals(graph: FieldGraph, fields: Mapping[str, _Point]) -> dict[str, _Point]:
    return {
        node.id: _beside(
            tuple(
                fields[other]
                for edge in graph.edges
                for mine, other in (
                    (edge.source, edge.target),
                    (edge.target, edge.source),
                )
                if mine == node.id and other in fields
            )
        )
        for node in graph.nodes
        if node.kind is not NodeKind.FIELD
    }


def layout(graph: FieldGraph, clusters: ClusterSet) -> dict[str, _Point]:
    groups = (
        *(cluster.members for cluster in clusters.clusters),
        *((member,) for member in clusters.isolated),
    )
    widths = tuple(2 * _radius(len(group)) + GAP for group in groups)
    row_width = max(math.sqrt(sum(w * w for w in widths)), max(widths, default=GAP))
    cursor = reduce(lambda c, w: _placed(row_width, c, w), widths, _Cursor())
    fields = {
        member: point
        for group, centre in zip(groups, cursor.centres, strict=True)
        for member, point in _ring(group, centre).items()
    }
    return {**fields, **_terminals(graph, fields)}
