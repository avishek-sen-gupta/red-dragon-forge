"""Thin query helpers over a merged knowledge graph (networkx.MultiDiGraph)."""

from __future__ import annotations

import networkx as nx
from interpreter.project.graph_types import EdgeKind, NodeKind

NodeId = tuple[NodeKind, str]


def _filtered_view(graph: nx.MultiDiGraph, edge_kinds: set[EdgeKind] | None) -> nx.MultiDiGraph:
    if edge_kinds is None:
        return graph
    view = nx.MultiDiGraph()
    view.add_nodes_from(graph.nodes(data=True))
    for u, v, data in graph.edges(data=True):
        if data["kind"] in edge_kinds:
            view.add_edge(u, v, **data)
    return view


def reachable_from(
    graph: nx.MultiDiGraph,
    start: NodeId,
    *,
    edge_kinds: set[EdgeKind] | None = None,
) -> set[NodeId]:
    """Every node reachable from start, optionally restricted to edge_kinds.
    start itself is not included."""
    view = _filtered_view(graph, edge_kinds)
    if start not in view:
        return set()
    return set(nx.descendants(view, start))


def callers_of(
    graph: nx.MultiDiGraph,
    target: NodeId,
    *,
    edge_kinds: set[EdgeKind] | None = None,
) -> set[NodeId]:
    """Every node with a direct edge into target, optionally restricted to edge_kinds."""
    if target not in graph:
        return set()
    callers: set[NodeId] = set()
    for source, _target, data in graph.in_edges(target, data=True):
        if edge_kinds is None or data["kind"] in edge_kinds:
            callers.add(source)
    return callers


def paths_between(
    graph: nx.MultiDiGraph,
    source: NodeId,
    target: NodeId,
    *,
    edge_kinds: set[EdgeKind] | None = None,
) -> list[list[NodeId]]:
    """All simple paths from source to target, optionally restricted to edge_kinds."""
    view = _filtered_view(graph, edge_kinds)
    if source not in view or target not in view:
        return []
    return list(nx.all_simple_paths(view, source, target))
