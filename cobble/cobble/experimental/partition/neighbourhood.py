"""One program's neighbourhood: its own nodes, every node one edge from them, and every node one edge from a dataset slot among those."""

from __future__ import annotations

from collections.abc import Iterable

from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_index import GraphIndex
from cobble.experimental.partition.node_kind import NodeKind


def _near(index: GraphIndex, nodes: Iterable[str]) -> frozenset[str]:
    return frozenset(
        end
        for node in nodes
        for number in index.touching.get(node, ())
        for end in (index.edges[number].source, index.edges[number].target)
    )


def _kept(index: GraphIndex, program: str) -> frozenset[str]:
    own = frozenset(index.programs[program])
    near = own | _near(index, own)
    slots = (node for node in near if index.nodes[node].kind is NodeKind.DATASET)
    return near | _near(index, slots)


def neighbourhood(index: GraphIndex, program: str) -> FieldGraph:
    kept = _kept(index, program)
    numbers = sorted(
        {
            number
            for node in kept
            for number in index.touching.get(node, ())
            if index.edges[number].source in kept and index.edges[number].target in kept
        }
    )
    return FieldGraph(
        nodes=tuple(index.nodes[node] for node in sorted(kept)),
        edges=tuple(index.edges[number] for number in numbers),
    )
