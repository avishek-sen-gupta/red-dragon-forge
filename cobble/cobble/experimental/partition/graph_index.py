"""The field graph indexed once: nodes by id, each node's edges, and each program's nodes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter

from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind


@dataclass(frozen=True)
class GraphIndex:
    """``touching[id]`` the positions in ``edges`` of every edge with ``id`` as an end; ``programs[name]`` the ids of that program's nodes, sorted."""

    nodes: Mapping[str, GraphNode]
    edges: tuple[GraphEdge, ...]
    touching: Mapping[str, tuple[int, ...]]
    programs: Mapping[str, tuple[str, ...]]


def _touching(edges: tuple[GraphEdge, ...]) -> Mapping[str, tuple[int, ...]]:
    ends = sorted(
        {
            (end, number)
            for number, edge in enumerate(edges)
            for end in (edge.source, edge.target)
        }
    )
    return {
        node: tuple(end[1] for end in group)
        for node, group in groupby(ends, itemgetter(0))
    }


def _programs(graph: FieldGraph) -> Mapping[str, tuple[str, ...]]:
    owned = sorted(
        (node.program, node.id)
        for node in graph.nodes
        if node.kind is not NodeKind.DATASET
    )
    return {
        name: tuple(pair[1] for pair in group)
        for name, group in groupby(owned, itemgetter(0))
    }


def graph_index(graph: FieldGraph) -> GraphIndex:
    return GraphIndex(
        nodes={node.id: node for node in graph.nodes},
        edges=graph.edges,
        touching=_touching(graph.edges),
        programs=_programs(graph),
    )
