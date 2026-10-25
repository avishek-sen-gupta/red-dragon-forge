"""Clusters a field graph: connected components inside each program, split by Louvain when large."""

from __future__ import annotations

import networkx as nx
from cobble.experimental.partition.cluster import Cluster
from cobble.experimental.partition.cluster_set import ClusterSet
from cobble.experimental.partition.field_components import clustered_graph, ordered
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.node_kind import NodeKind
from cobble.experimental.partition.progress import counted
from cobble.experimental.partition.tally import CLUSTERS, Tally

LOUVAIN_SEED = 7
STEP = 100

_Members = tuple[str, ...]


def _communities(
    graph: nx.Graph[str], members: _Members, split_at: int
) -> tuple[_Members, ...]:
    if len(members) < split_at:
        return (members,)
    return ordered(
        nx.community.louvain_communities(graph.subgraph(members), seed=LOUVAIN_SEED)
    )


def cluster_set(graph: FieldGraph, split_at: int) -> ClusterSet:
    fields = {
        node.id: node.program for node in graph.nodes if node.kind is NodeKind.FIELD
    }
    clustered = clustered_graph(graph)
    components = ordered(nx.connected_components(clustered))
    found = tuple(
        (index, members)
        for index, component in enumerate(
            counted(
                components,
                Tally(CLUSTERS, "components clustered", STEP),
                len(components),
            )
        )
        for members in _communities(clustered, component, split_at)
    )
    grouped = {member for _, members in found for member in members}
    return ClusterSet(
        clusters=tuple(
            Cluster(
                id=i, component=component, program=fields[members[0]], members=members
            )
            for i, (component, members) in enumerate(found)
        ),
        isolated=tuple(sorted(set(fields) - grouped)),
    )
