"""Unit tests for merge_graph()."""

from knowledge_graph.merge import merge_graph
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def test_nodes_are_keyed_by_kind_and_id():
    nodes = [GraphNode(id="MAIN", kind=NodeKind.PROGRAM)]
    graph = merge_graph(nodes, [])
    assert graph.has_node((NodeKind.PROGRAM, "MAIN"))
    assert graph.nodes[(NodeKind.PROGRAM, "MAIN")]["id"] == "MAIN"
    assert graph.nodes[(NodeKind.PROGRAM, "MAIN")]["kind"] is NodeKind.PROGRAM


def test_program_and_dataset_with_same_id_do_not_collide():
    nodes = [
        GraphNode(id="ACCTFILE", kind=NodeKind.PROGRAM),
        GraphNode(id="ACCTFILE", kind=NodeKind.DATASET),
    ]
    graph = merge_graph(nodes, [])
    assert graph.has_node((NodeKind.PROGRAM, "ACCTFILE"))
    assert graph.has_node((NodeKind.DATASET, "ACCTFILE"))
    assert graph.number_of_nodes() == 2


def test_duplicate_node_registration_merges_attrs_not_overwrites():
    nodes = [
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM, attrs={"a": 1}),
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM, attrs={"b": 2}),
    ]
    graph = merge_graph(nodes, [])
    assert graph.nodes[(NodeKind.PROGRAM, "MAIN")]["attrs"] == {"a": 1, "b": 2}


def test_duplicate_node_registration_prefers_non_none_file_path():
    nodes = [
        GraphNode(id="HELPER", kind=NodeKind.PROGRAM, file_path=None),
        GraphNode(id="HELPER", kind=NodeKind.PROGRAM, file_path="/src/HELPER.cbl"),
    ]
    graph = merge_graph(nodes, [])
    assert graph.nodes[(NodeKind.PROGRAM, "HELPER")]["file_path"] == "/src/HELPER.cbl"


def test_edge_added_between_existing_nodes():
    nodes = [
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM),
        GraphNode(id="HELPER", kind=NodeKind.PROGRAM),
    ]
    edges = [
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="HELPER",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        )
    ]
    graph = merge_graph(nodes, edges)
    assert graph.has_edge((NodeKind.PROGRAM, "MAIN"), (NodeKind.PROGRAM, "HELPER"))
    edge_data = graph.get_edge_data(
        (NodeKind.PROGRAM, "MAIN"), (NodeKind.PROGRAM, "HELPER")
    )
    assert edge_data[0]["kind"] is EdgeKind.CALL


def test_two_edges_of_different_kinds_between_same_nodes_both_kept():
    """MultiDiGraph, not DiGraph: a program that both CALLs another program
    and also runs it as a JCL step's PGM= keeps both edges."""
    nodes = [
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM),
        GraphNode(id="HELPER", kind=NodeKind.PROGRAM),
    ]
    edges = [
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="HELPER",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        ),
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="HELPER",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.XCTL,
        ),
    ]
    graph = merge_graph(nodes, edges)
    edge_data = graph.get_edge_data(
        (NodeKind.PROGRAM, "MAIN"), (NodeKind.PROGRAM, "HELPER")
    )
    kinds = {d["kind"] for d in edge_data.values()}
    assert kinds == {EdgeKind.CALL, EdgeKind.XCTL}


def test_edge_endpoint_missing_from_nodes_list_is_created_defensively():
    """An edge whose endpoint wasn't separately listed in nodes still merges
    cleanly — data from three independent extractors is not guaranteed to
    perfectly enumerate every node an edge references."""
    edges = [
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="HELPER",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        )
    ]
    graph = merge_graph([], edges)
    assert graph.has_node((NodeKind.PROGRAM, "MAIN"))
    assert graph.has_node((NodeKind.PROGRAM, "HELPER"))
