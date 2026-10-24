"""Places every node organically: each cluster a force-laid group inside its program, groups and lone nodes scattered and pushed apart, programs placed by a force layout over what links them and pushed apart, dataset slots among the fields they link."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from functools import reduce
from itertools import combinations

import networkx as nx
import numpy as np
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.node_kind import NodeKind
from cobble.experimental.partition.progress import counted
from cobble.experimental.partition.tally import RENDER, Tally
from numpy.typing import NDArray

LAYOUT_SEED = 7
SPREAD = 2.2
GAP = 4.0
DOT = 1.4
SCATTER = 1.3
SPREAD_STEPS = 200
JITTER = 1.5
SETTLE_STEPS = 3000

_Point = tuple[float, float]
_Points = NDArray[np.float64]


def _radius(size: int) -> float:
    return SPREAD * math.sqrt(size) + 1.0


def _programs(graph: FieldGraph) -> dict[str, tuple[str, ...]]:
    owned = sorted(
        (node.program, node.id)
        for node in graph.nodes
        if node.kind is not NodeKind.DATASET
    )
    names = sorted({program for program, _ in owned})
    return {
        name: tuple(node for program, node in owned if program == name)
        for name in names
    }


def _local(graph: FieldGraph, members: Sequence[str]) -> nx.Graph[str]:
    inside = frozenset(members)
    local: nx.Graph[str] = nx.Graph()
    local.add_nodes_from(members)
    local.add_edges_from(
        (edge.source, edge.target)
        for edge in graph.edges
        if edge.source in inside and edge.target in inside
    )
    return local


def _component(local: nx.Graph[str], members: Sequence[str]) -> _Points:
    if len(members) == 1:
        return np.zeros((1, 2), dtype=np.float64)
    placed = nx.spring_layout(local.subgraph(members), seed=LAYOUT_SEED)
    raw = np.array([placed[member] for member in members], dtype=np.float64)
    spread = raw - raw.mean(axis=0)
    reach = max(float(np.linalg.norm(spread, axis=1).max()), 1e-9)
    return spread * (_radius(len(members)) / reach)


def _scattered(radii: _Points) -> _Points:
    area = math.sqrt(float((radii**2).sum())) * SCATTER
    rng = np.random.default_rng(LAYOUT_SEED)
    angles = rng.uniform(0, 2 * math.pi, len(radii))
    reach = area * np.sqrt(rng.uniform(0, 1, len(radii)))
    start = np.stack((reach * np.cos(angles), reach * np.sin(angles)), axis=1)
    return _apart(start, radii, DOT, SPREAD_STEPS)


def _groups(
    members: Sequence[str], cluster_of: Mapping[str, int]
) -> tuple[tuple[str, ...], ...]:
    clusters = sorted(
        {cluster_of[member] for member in members if member in cluster_of}
    )
    return (
        *(
            tuple(member for member in members if cluster_of.get(member) == cluster)
            for cluster in clusters
        ),
        *((member,) for member in members if member not in cluster_of),
    )


def _region(
    graph: FieldGraph, members: Sequence[str], cluster_of: Mapping[str, int]
) -> dict[str, _Point]:
    local = _local(graph, members)
    groups = _groups(members, cluster_of)
    shapes = tuple(_component(local, group) for group in groups)
    radii = np.array(
        [float(np.linalg.norm(shape, axis=1).max()) + DOT for shape in shapes],
        dtype=np.float64,
    )
    centres = _scattered(radii)
    placed = {
        member: centre + point
        for group, shape, centre in zip(groups, shapes, centres, strict=True)
        for member, point in zip(group, shape, strict=True)
    }
    middle = np.array(list(placed.values()), dtype=np.float64).mean(axis=0)
    return {
        member: (float(point[0] - middle[0]), float(point[1] - middle[1]))
        for member, point in placed.items()
    }


def _ties(graph: FieldGraph, owner: Mapping[str, str]) -> Counter[tuple[str, str]]:
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
            sorted(
                {
                    owner[end]
                    for edge in graph.edges
                    if slot in (edge.source, edge.target)
                    for end in (edge.source, edge.target)
                    if end in owner
                }
            ),
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
    return reduce(
        lambda centres, _: (
            centres if _settled(centres, radii, gap) else _pushed(centres, radii, gap)
        ),
        range(steps),
        start.reshape(-1, 2),
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


def _slots(graph: FieldGraph, points: Mapping[str, _Point]) -> dict[str, _Point]:
    slots = sorted(node.id for node in graph.nodes if node.kind is NodeKind.DATASET)
    shakes = np.random.default_rng(LAYOUT_SEED).uniform(
        -JITTER, JITTER, (len(slots), 2)
    )
    return {
        slot: (float(centre[0] + shake[0]), float(centre[1] + shake[1]))
        for slot, shake in zip(slots, shakes, strict=True)
        for centre in (_among(graph, points, slot),)
    }


def _among(graph: FieldGraph, points: Mapping[str, _Point], slot: str) -> _Points:
    ends = [
        points[end]
        for edge in graph.edges
        if slot in (edge.source, edge.target)
        for end in (edge.source, edge.target)
        if end in points
    ]
    return (
        np.array(ends, dtype=np.float64).reshape(-1, 2).mean(axis=0)
        if ends
        else np.zeros(2)
    )


def layout(graph: FieldGraph, cluster_of: Mapping[str, int]) -> dict[str, _Point]:
    programs = _programs(graph)
    names = tuple(programs)
    owner = {node: name for name, members in programs.items() for node in members}
    regions = {
        name: _region(graph, programs[name], cluster_of)
        for name in counted(names, Tally(RENDER, "programs laid out", 1), len(names))
    }
    radii = np.array(
        [
            max(math.hypot(x, y) for x, y in regions[name].values()) + DOT
            for name in names
        ],
        dtype=np.float64,
    )
    centres = _centres(names, radii, _ties(graph, owner))
    points = {
        node: (x + float(centre[0]), y + float(centre[1]))
        for name, centre in zip(names, centres, strict=True)
        for node, (x, y) in regions[name].items()
    }
    return {**points, **_slots(graph, points)}
