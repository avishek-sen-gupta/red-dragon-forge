"""merge_graph() — combine GraphNode/GraphEdge sequences from every
extractor (red-dragon's CALL/COPY graph, cicada's CICS flow graph, jackal's
JCL graph) into one networkx.MultiDiGraph, keyed by (kind, id).
"""

from __future__ import annotations

import networkx as nx

from cobble.interpreter.project.graph_types import GraphEdge, GraphNode


def merge_graph(nodes: list[GraphNode], edges: list[GraphEdge]) -> nx.MultiDiGraph:
    """Build one MultiDiGraph from GraphNode/GraphEdge sequences.

    Nodes are keyed by (kind, id). When `nodes` comes from GraphWriter's
    output, every key already appears at most once with its file_path fully
    resolved by CorpusIndex (see graph_writer.py) — the attrs-union/
    file-path-prefers-non-None merge below is now a defensive no-op in that
    case, not something normal input relies on. It's kept for robustness
    against callers that pass in raw, not-yet-deduped GraphNode/GraphEdge
    sequences directly (e.g. hand-built test fixtures). MultiDiGraph (not
    DiGraph): two nodes can be legitimately connected by more than one edge
    kind. Edges reference their endpoints' (kind, id) directly via
    GraphEdge.source_kind/target_kind — endpoints not separately present in
    `nodes` are added defensively so a merge from three independent
    extractors never KeyErrors on an under-enumerated node list.
    """
    graph = nx.MultiDiGraph()

    for node in nodes:
        key = (node.kind, node.id)
        if graph.has_node(key):
            data = graph.nodes[key]
            data["attrs"] = {**data["attrs"], **node.attrs}
            data["file_path"] = data["file_path"] or node.file_path
        else:
            graph.add_node(
                key,
                kind=node.kind,
                id=node.id,
                file_path=node.file_path,
                attrs=dict(node.attrs),
            )

    for edge in edges:
        source_key = (edge.source_kind, edge.source)
        target_key = (edge.target_kind, edge.target)
        if not graph.has_node(source_key):
            graph.add_node(
                source_key,
                kind=edge.source_kind,
                id=edge.source,
                file_path=None,
                attrs={},
            )
        if not graph.has_node(target_key):
            graph.add_node(
                target_key,
                kind=edge.target_kind,
                id=edge.target,
                file_path=None,
                attrs={},
            )
        graph.add_edge(source_key, target_key, kind=edge.kind, attrs=dict(edge.attrs))

    return graph
