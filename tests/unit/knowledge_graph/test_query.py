"""Unit tests for the query helpers over a merged graph."""

from knowledge_graph.merge import merge_graph
from knowledge_graph.query import callers_of, paths_between, reachable_from
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def _chain_graph():
    """MAIN -CALL-> MID -CALL-> LEAF, plus MAIN -COPY-> RECRD (a dead end)."""
    nodes = [
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM),
        GraphNode(id="MID", kind=NodeKind.PROGRAM),
        GraphNode(id="LEAF", kind=NodeKind.PROGRAM),
        GraphNode(id="RECRD", kind=NodeKind.COPYBOOK),
    ]
    edges = [
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="MID",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        ),
        GraphEdge(
            source="MID",
            source_kind=NodeKind.PROGRAM,
            target="LEAF",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        ),
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="RECRD",
            target_kind=NodeKind.COPYBOOK,
            kind=EdgeKind.COPY,
        ),
    ]
    return merge_graph(nodes, edges)


def test_reachable_from_finds_the_whole_downstream_chain():
    graph = _chain_graph()
    result = reachable_from(graph, (NodeKind.PROGRAM, "MAIN"))
    assert result == {
        (NodeKind.PROGRAM, "MID"),
        (NodeKind.PROGRAM, "LEAF"),
        (NodeKind.COPYBOOK, "RECRD"),
    }


def test_reachable_from_can_be_restricted_by_edge_kind():
    graph = _chain_graph()
    result = reachable_from(
        graph, (NodeKind.PROGRAM, "MAIN"), edge_kinds={EdgeKind.CALL}
    )
    assert result == {(NodeKind.PROGRAM, "MID"), (NodeKind.PROGRAM, "LEAF")}


def test_reachable_from_unknown_start_is_empty():
    graph = _chain_graph()
    result = reachable_from(graph, (NodeKind.PROGRAM, "GHOST"))
    assert result == set()


def test_callers_of_finds_direct_predecessors():
    graph = _chain_graph()
    result = callers_of(graph, (NodeKind.PROGRAM, "LEAF"))
    assert result == {(NodeKind.PROGRAM, "MID")}


def test_callers_of_can_be_restricted_by_edge_kind():
    graph = _chain_graph()
    result = callers_of(graph, (NodeKind.COPYBOOK, "RECRD"), edge_kinds={EdgeKind.CALL})
    assert result == set()


def test_paths_between_returns_the_full_chain():
    graph = _chain_graph()
    paths = paths_between(graph, (NodeKind.PROGRAM, "MAIN"), (NodeKind.PROGRAM, "LEAF"))
    assert paths == [
        [
            (NodeKind.PROGRAM, "MAIN"),
            (NodeKind.PROGRAM, "MID"),
            (NodeKind.PROGRAM, "LEAF"),
        ]
    ]


def test_paths_between_unreachable_nodes_is_empty():
    graph = _chain_graph()
    paths = paths_between(graph, (NodeKind.PROGRAM, "LEAF"), (NodeKind.PROGRAM, "MAIN"))
    assert paths == []
