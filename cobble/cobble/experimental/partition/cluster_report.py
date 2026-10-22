"""The clusters as a markdown report, for reading by hand."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from itertools import groupby

from cobble.experimental.partition.cluster import Cluster
from cobble.experimental.partition.cluster_set import ClusterSet
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind

TERMINALS_SHOWN = 8


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _terminals(
    graph: FieldGraph, nodes: Mapping[str, GraphNode], members: set[str]
) -> tuple[str, ...]:
    touching = Counter(
        nodes[other].label
        for edge in graph.edges
        for mine, other in ((edge.source, edge.target), (edge.target, edge.source))
        if mine in members and nodes[other].kind is not NodeKind.FIELD
    )
    ranked = sorted((-n, label) for label, n in touching.items())
    return tuple(label for _, label in ranked[:TERMINALS_SHOWN])


def _cluster_lines(cluster: Cluster, nodes: Mapping[str, GraphNode]) -> tuple[str, ...]:
    records = Counter(nodes[member].record for member in cluster.members).most_common()
    return (
        f"- cluster {cluster.id}, {_count(len(cluster.members), 'field')}; records "
        + ", ".join(f"{record} ({n})" for record, n in records),
        "  - " + ", ".join(sorted(nodes[member].label for member in cluster.members)),
    )


def _component_lines(
    graph: FieldGraph,
    nodes: Mapping[str, GraphNode],
    index: int,
    clusters: Sequence[Cluster],
) -> tuple[str, ...]:
    members = {member for cluster in clusters for member in cluster.members}
    terminals = _terminals(graph, nodes, members)
    return (
        "",
        f"## Component {index}: {clusters[0].program}, {_count(len(members), 'field')}",
        "",
        *((f"terminals: {'; '.join(terminals)}", "") if terminals else ()),
        *(line for cluster in clusters for line in _cluster_lines(cluster, nodes)),
    )


def _component(cluster: Cluster) -> int:
    return cluster.component


def cluster_report(graph: FieldGraph, clusters: ClusterSet) -> str:
    nodes = {node.id: node for node in graph.nodes}
    components = tuple(
        (index, tuple(group)) for index, group in groupby(clusters.clusters, _component)
    )
    lines = (
        f"# Field partitions (barrier {graph.barrier})",
        "",
        f"{_count(len(components), 'component')} of 2+ fields, "
        f"{_count(len(clusters.clusters), 'cluster')}, "
        f"{_count(len(clusters.isolated), 'isolated field')}.",
        *(
            line
            for index, group in components
            for line in _component_lines(graph, nodes, index, group)
        ),
    )
    return "\n".join(lines) + "\n"
