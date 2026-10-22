"""Places every node: fields linked by clustered field edges share a disc, discs pack apart, the rest ring them."""

from __future__ import annotations

import math
from collections.abc import Sequence
from functools import reduce
from itertools import accumulate, count

import networkx as nx
import numpy as np
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.node_kind import NodeKind
from numpy.typing import NDArray

LAYOUT_SEED = 7
SPREAD = 1.6
GAP = 4.0
DOT = 2.6
SETTLE_STEPS = 3000

_Point = tuple[float, float]
_Points = NDArray[np.float64]
_GOLDEN = math.pi * (3 - math.sqrt(5))


def _links(graph: FieldGraph) -> nx.Graph[str]:
    fields = {node.id for node in graph.nodes if node.kind is NodeKind.FIELD}
    links: nx.Graph[str] = nx.Graph()
    links.add_edges_from(
        (edge.source, edge.target)
        for edge in graph.edges
        if edge.clustered and edge.source in fields and edge.target in fields
    )
    return links


def _groups(links: nx.Graph[str]) -> tuple[tuple[str, ...], ...]:
    ranked = sorted(
        (-len(group), tuple(sorted(group))) for group in nx.connected_components(links)
    )
    return tuple(group for _, group in ranked)


def _radius(size: int) -> float:
    return SPREAD * math.sqrt(size) + 1.0


def _spiral(radii: _Points) -> _Points:
    step = 2 * float(radii.sum()) / max(len(radii), 1) + GAP
    turns = tuple(
        (math.sqrt(i) * math.cos(i * _GOLDEN), math.sqrt(i) * math.sin(i * _GOLDEN))
        for i in range(len(radii))
    )
    return np.array(turns, dtype=np.float64).reshape(-1, 2) * step


def _overlap(centres: _Points, radii: _Points) -> _Points:
    apart = np.linalg.norm(centres[:, None, :] - centres[None, :, :], axis=-1)
    needed = radii[:, None] + radii[None, :] + GAP
    return np.clip(needed - apart, 0, None) * (1 - np.eye(len(radii)))


def _pushed(centres: _Points, radii: _Points) -> _Points:
    offsets = centres[:, None, :] - centres[None, :, :]
    apart = np.linalg.norm(offsets, axis=-1) + np.eye(len(radii))
    push = offsets / apart[..., None] * _overlap(centres, radii)[..., None] / 2
    return centres + push.sum(axis=1) / 2


def _settled(centres: _Points, radii: _Points) -> bool:
    return float(_overlap(centres, radii).max(initial=0.0)) < 1e-3


def _packed(radii: _Points) -> _Points:
    return reduce(
        lambda centres, _: (
            centres if _settled(centres, radii) else _pushed(centres, radii)
        ),
        range(SETTLE_STEPS),
        _spiral(radii),
    )


def _disc(
    links: nx.Graph[str], group: Sequence[str], centre: _Points
) -> dict[str, _Point]:
    placed = nx.spring_layout(links.subgraph(group), seed=LAYOUT_SEED)
    raw = np.array([placed[member] for member in group], dtype=np.float64)
    spread = raw - raw.mean(axis=0)
    reach = max(float(np.linalg.norm(spread, axis=1).max()), 1e-9)
    scaled = centre + spread * (_radius(len(group)) / reach)
    return {
        member: (float(point[0]), float(point[1]))
        for member, point in zip(group, scaled, strict=True)
    }


def _ring(start: float, k: int) -> tuple[float, int]:
    radius = start + k * DOT
    return radius, max(1, int(2 * math.pi * radius / DOT))


def _rings(start: float, total: int) -> tuple[tuple[float, int], ...]:
    filled = accumulate((_ring(start, k)[1] for k in count()), initial=0)
    needed = next(k for k, placed in enumerate(filled) if placed >= total)
    rings = tuple(_ring(start, k) for k in range(needed))
    before = tuple(accumulate((size for _, size in rings), initial=0))[:-1]
    return tuple(
        (radius, min(size, total - placed))
        for (radius, size), placed in zip(rings, before, strict=True)
    )


def _band(nodes: Sequence[str], start: float) -> dict[str, _Point]:
    slots = tuple(
        (radius * math.cos(angle), radius * math.sin(angle))
        for radius, size in _rings(start, len(nodes))
        for angle in (2 * math.pi * j / size + radius for j in range(size))
    )
    return dict(zip(nodes, slots, strict=True))


def layout(graph: FieldGraph) -> dict[str, _Point]:
    links = _links(graph)
    groups = _groups(links)
    radii = np.array([_radius(len(group)) for group in groups], dtype=np.float64)
    centres = _packed(radii)
    discs = {
        member: point
        for group, centre in zip(groups, centres, strict=True)
        for member, point in _disc(links, group, centre).items()
    }
    reach = float((np.linalg.norm(centres, axis=1) + radii).max(initial=0.0))
    ranked = sorted(
        (node.kind is not NodeKind.FIELD, node.program, node.id)
        for node in graph.nodes
        if node.id not in discs
    )
    rest = tuple(entry[2] for entry in ranked)
    return {**discs, **_band(rest, reach + 4 * GAP)}
