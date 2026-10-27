"""Places each program's patch, sized by its field count, by a force layout over what links the programs, pushed apart; starts each field evenly inside its patch and each dataset slot among the fields it links. The page lays the fields out inside their patches."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from itertools import accumulate, combinations, groupby
from operator import itemgetter

import networkx as nx
import numpy as np
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.node_kind import NodeKind
from cobble.experimental.partition.page_region import PageRegion
from cobble.experimental.partition.placement import Placement
from numpy.typing import NDArray

LAYOUT_SEED = 7
FORCE_STEPS = 100
GAP = 4.0
DOT = 1.4
JITTER = 1.5
SETTLE_STEPS = 3000
PATCH = 4.0
GOLDEN = math.pi * (3 - math.sqrt(5))

_Point = tuple[float, float]
_Points = NDArray[np.float64]
_Ends = Mapping[str, tuple[str, ...]]


def _programs(graph: FieldGraph) -> dict[str, tuple[str, ...]]:
    owned = sorted(
        (node.program, node.id)
        for node in graph.nodes
        if node.kind is not NodeKind.DATASET
    )
    return {
        name: tuple(node for _, node in group)
        for name, group in groupby(owned, itemgetter(0))
    }


def _ends(graph: FieldGraph) -> _Ends:
    steps = sorted(
        step
        for number, edge in enumerate(graph.edges)
        for step in (
            (edge.source, number, edge.target),
            (edge.target, number, edge.source),
        )
    )
    return {
        node: tuple(step[2] for step in group)
        for node, group in groupby(steps, itemgetter(0))
    }


def _radius(size: int) -> float:
    return PATCH * math.sqrt(size) + DOT


def _region(members: Sequence[str]) -> dict[str, _Point]:
    reach = _radius(len(members)) - DOT
    return {
        member: (
            reach * math.sqrt(i / len(members)) * math.cos(i * GOLDEN),
            reach * math.sqrt(i / len(members)) * math.sin(i * GOLDEN),
        )
        for i, member in enumerate(members)
    }


def _ties(
    graph: FieldGraph, ends: _Ends, owner: Mapping[str, str]
) -> Counter[tuple[str, str]]:
    slots = {node.id for node in graph.nodes if node.kind is NodeKind.DATASET}
    direct = (
        tuple(sorted((owner[edge.source], owner[edge.target])))
        for edge in graph.edges
        if edge.source in owner
        and edge.target in owner
        and owner[edge.source] != owner[edge.target]
    )
    through = (
        pair
        for slot in sorted(slots)
        for pair in combinations(
            sorted({owner[end] for end in ends.get(slot, ()) if end in owner}),
            2,
        )
    )
    return Counter((pair[0], pair[1]) for pair in (*direct, *through))


def _overlap(centres: _Points, radii: _Points, gap: float) -> _Points:
    apart = np.linalg.norm(centres[:, None, :] - centres[None, :, :], axis=-1)
    needed = radii[:, None] + radii[None, :] + gap
    return np.clip(needed - apart, 0, None) * (1 - np.eye(len(radii)))


def _pushed(centres: _Points, radii: _Points, gap: float) -> _Points:
    offsets = centres[:, None, :] - centres[None, :, :]
    apart = np.linalg.norm(offsets, axis=-1) + np.eye(len(radii))
    push = offsets / apart[..., None] * _overlap(centres, radii, gap)[..., None] / 2
    return centres + push.sum(axis=1) / 2


def _settled(centres: _Points, radii: _Points, gap: float) -> bool:
    return float(_overlap(centres, radii, gap).max(initial=0.0)) < 1e-3


def _apart(start: _Points, radii: _Points, gap: float, steps: int) -> _Points:
    tried = accumulate(
        range(steps),
        lambda centres, _: _pushed(centres, radii, gap),
        initial=start.reshape(-1, 2),
    )
    return next(
        centres
        for step, centres in enumerate(tried)
        if step == steps or _settled(centres, radii, gap)
    )


def _centres(
    names: Sequence[str], radii: _Points, ties: Counter[tuple[str, str]]
) -> _Points:
    linked: nx.Graph[str] = nx.Graph()
    linked.add_nodes_from(names)
    linked.add_weighted_edges_from((a, b, float(n)) for (a, b), n in ties.items())
    placed = nx.spring_layout(linked, seed=LAYOUT_SEED, weight="weight")
    scale = 2 * math.sqrt(float((radii**2).sum()))
    start = np.array([placed[name] for name in names], dtype=np.float64) * scale
    return _apart(start, radii, GAP, SETTLE_STEPS)


def _slots(
    graph: FieldGraph, ends: _Ends, points: Mapping[str, _Point]
) -> dict[str, _Point]:
    slots = sorted(node.id for node in graph.nodes if node.kind is NodeKind.DATASET)
    shakes = np.random.default_rng(LAYOUT_SEED).uniform(
        -JITTER, JITTER, (len(slots), 2)
    )
    return {
        slot: (float(centre[0] + shake[0]), float(centre[1] + shake[1]))
        for slot, shake in zip(slots, shakes, strict=True)
        for centre in (_among(ends, points, slot),)
    }


def _among(ends: _Ends, points: Mapping[str, _Point], slot: str) -> _Points:
    near = [points[end] for end in ends.get(slot, ()) if end in points]
    return (
        np.array(near, dtype=np.float64).reshape(-1, 2).mean(axis=0)
        if near
        else np.zeros(2)
    )


def layout(graph: FieldGraph) -> Placement:
    programs = _programs(graph)
    ends = _ends(graph)
    names = tuple(programs)
    owner = {node: name for name, members in programs.items() for node in members}
    regions = {name: _region(programs[name]) for name in names}
    radii = np.array([_radius(len(programs[name])) for name in names], dtype=np.float64)
    centres = _centres(names, radii, _ties(graph, ends, owner))
    points = {
        node: (x + float(centre[0]), y + float(centre[1]))
        for name, centre in zip(names, centres, strict=True)
        for node, (x, y) in regions[name].items()
    }
    return Placement(
        points={**points, **_slots(graph, ends, points)},
        regions=tuple(
            PageRegion(
                program=name,
                x=float(centre[0]),
                y=float(centre[1]),
                radius=float(radius),
            )
            for name, centre, radius in zip(names, centres, radii, strict=True)
        ),
    )
