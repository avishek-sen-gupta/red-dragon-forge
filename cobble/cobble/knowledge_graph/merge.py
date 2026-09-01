"""merge_graph() — combine GraphNode/GraphEdge sequences from every
extractor (red-dragon's CALL/COPY graph, cicada's CICS flow graph, jackal's
JCL graph) into one networkx.MultiDiGraph, keyed by (kind, id).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from functools import reduce
from itertools import chain, groupby
from pathlib import Path
from types import MappingProxyType

import networkx as nx

from cobble.file_location import FileLocation, FileLocationReason, NoFileLocation
from cobble.interpreter.project.graph_types import GraphEdge, GraphNode

# Every reason states something about the node except this one, which states
# only that nothing was asked -- so it alone ranks below a stated reason.
_STANDING_OF_REASON: Mapping[FileLocationReason, int] = MappingProxyType(
    {FileLocationReason.NOT_ATTEMPTED: 0}
)


def _sort_key(node: GraphNode) -> tuple[str, str]:
    """The node's identity, in something orderable: NodeKind is an Enum."""
    return (node.kind.value, node.id)


def _standing(location: FileLocation) -> int:
    """How much a location claims — a file, a reason for having none, silence.

    Ranked rather than compared pairwise so the fold below is a max and the
    precedence is a single list to read. NOT_ATTEMPTED ranks lowest because it
    is the one value that asserts nothing: a node reached only through an edge
    endpoint was never looked up, so it must not overwrite what a resolver
    said about the same node somewhere else.
    """
    match location:
        case Path():
            return 2
        case NoFileLocation(reason=reason):
            return _STANDING_OF_REASON.get(reason, 1)


def _folded(first: GraphNode, second: GraphNode) -> GraphNode:
    """Two occurrences of one (kind, id), as the single node the graph keeps.

    Ties in standing go to the earlier occurrence, which is GraphWriter's own
    keep-first rule — so merging its output back in cannot contradict what it
    already wrote. attrs union with the later occurrence winning a shared key.
    """
    return GraphNode(
        id=first.id,
        kind=first.kind,
        location=(
            first.location
            if _standing(first.location) >= _standing(second.location)
            else second.location
        ),
        attrs={**first.attrs, **second.attrs},
    )


def _endpoints(edges: Sequence[GraphEdge]) -> Iterable[GraphNode]:
    """Both ends of every edge, as nodes.

    Edges reference their endpoints' (kind, id) directly, so a merge from three
    independent extractors would otherwise KeyError on an under-enumerated node
    list. These carry the default location — NOT_ATTEMPTED — because there is no
    CorpusIndex here to ask, and they lose to any enumerated occurrence.
    """
    return chain.from_iterable(
        (
            GraphNode(id=edge.source, kind=edge.source_kind),
            GraphNode(id=edge.target, kind=edge.target_kind),
        )
        for edge in edges
    )


def _unique(nodes: Iterable[GraphNode]) -> Iterable[GraphNode]:
    """One node per (kind, id), repeated occurrences folded together.

    Sorted, so the graph's node order is a function of the graph rather than of
    which extractor happened to run first. Sorting is also what makes the fold
    a groupby instead of a dict built by mutation.
    """
    return (
        reduce(_folded, group)
        for _key, group in groupby(sorted(nodes, key=_sort_key), key=_sort_key)
    )


def merge_graph(
    nodes: Sequence[GraphNode], edges: Sequence[GraphEdge]
) -> nx.MultiDiGraph:
    """Build one MultiDiGraph from GraphNode/GraphEdge sequences.

    Nodes are keyed by (kind, id). When `nodes` comes from GraphWriter's
    output, every key already appears at most once with its location fully
    resolved by CorpusIndex (see graph_writer.py) — the fold in _folded is a
    defensive no-op in that case, not something normal input relies on. It is
    kept for callers that pass raw, not-yet-deduped sequences directly (e.g.
    hand-built test fixtures). MultiDiGraph (not DiGraph): two nodes can be
    legitimately connected by more than one edge kind.
    """
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(
        (
            (node.kind, node.id),
            {
                "kind": node.kind,
                "id": node.id,
                "location": node.location,
                "attrs": dict(node.attrs),
            },
        )
        for node in _unique(chain(nodes, _endpoints(edges)))
    )
    graph.add_edges_from(
        (
            (edge.source_kind, edge.source),
            (edge.target_kind, edge.target),
            {"kind": edge.kind, "attrs": dict(edge.attrs)},
        )
        for edge in edges
    )
    return graph
