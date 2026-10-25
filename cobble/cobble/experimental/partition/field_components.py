"""The connected components of a field graph: fields of one program joined by edges clustering may cross."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import networkx as nx
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.node_kind import NodeKind

_Members = tuple[str, ...]


def ordered(groups: Iterable[Iterable[str]]) -> tuple[_Members, ...]:
    sized = (tuple(sorted(group)) for group in groups)
    ranked = sorted((-len(members), members) for members in sized)
    return tuple(members for _, members in ranked)


def clustered_graph(graph: FieldGraph) -> nx.Graph[str]:
    fields = {node.id for node in graph.nodes if node.kind is NodeKind.FIELD}
    return nx.Graph(
        [
            (edge.source, edge.target)
            for edge in graph.edges
            if edge.clustered
            and not edge.cross_program
            and edge.source in fields
            and edge.target in fields
        ]
    )


def component_of(graph: FieldGraph) -> Mapping[str, int]:
    """Each field in a component of two or more, by the component's rank, largest first."""
    return {
        member: index
        for index, members in enumerate(
            ordered(nx.connected_components(clustered_graph(graph)))
        )
        for member in members
    }
