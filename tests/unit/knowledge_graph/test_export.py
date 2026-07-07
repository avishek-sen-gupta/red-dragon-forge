"""Unit tests for NDJSON export/import round-tripping."""

from pathlib import Path

from knowledge_graph.export import read_ndjson, write_ndjson
from knowledge_graph.merge import merge_graph
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def _sample_graph():
    nodes = [
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM, file_path="/src/MAIN.cbl"),
        GraphNode(id="RECRD", kind=NodeKind.COPYBOOK, attrs={"note": "shared"}),
    ]
    edges = [
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="RECRD",
            target_kind=NodeKind.COPYBOOK,
            kind=EdgeKind.COPY,
            attrs={"line": 42},
        )
    ]
    return merge_graph(nodes, edges)


def test_write_ndjson_creates_both_files(tmp_path: Path):
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.ndjson"
    edges_path = tmp_path / "edges.ndjson"
    write_ndjson(graph, nodes_path, edges_path)
    assert nodes_path.is_file()
    assert edges_path.is_file()


def test_write_ndjson_one_line_per_node_and_edge(tmp_path: Path):
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.ndjson"
    edges_path = tmp_path / "edges.ndjson"
    write_ndjson(graph, nodes_path, edges_path)
    assert len(nodes_path.read_text().strip().splitlines()) == 2
    assert len(edges_path.read_text().strip().splitlines()) == 1


def test_read_ndjson_round_trips_nodes(tmp_path: Path):
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.ndjson"
    edges_path = tmp_path / "edges.ndjson"
    write_ndjson(graph, nodes_path, edges_path)
    nodes, _edges = read_ndjson(nodes_path, edges_path)
    by_id = {n.id: n for n in nodes}
    assert by_id["MAIN"].kind is NodeKind.PROGRAM
    assert by_id["MAIN"].file_path == "/src/MAIN.cbl"
    assert by_id["RECRD"].attrs == {"note": "shared"}


def test_read_ndjson_round_trips_edges(tmp_path: Path):
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.ndjson"
    edges_path = tmp_path / "edges.ndjson"
    write_ndjson(graph, nodes_path, edges_path)
    _nodes, edges = read_ndjson(nodes_path, edges_path)
    assert len(edges) == 1
    assert edges[0].source == "MAIN"
    assert edges[0].source_kind is NodeKind.PROGRAM
    assert edges[0].target == "RECRD"
    assert edges[0].target_kind is NodeKind.COPYBOOK
    assert edges[0].kind is EdgeKind.COPY
    assert edges[0].attrs == {"line": 42}


def test_round_trip_through_merge_graph_again_is_stable(tmp_path: Path):
    """read_ndjson's output feeds merge_graph() cleanly — the NDJSON seam
    the spec describes for a future graph-DB/visualization consumer."""
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.ndjson"
    edges_path = tmp_path / "edges.ndjson"
    write_ndjson(graph, nodes_path, edges_path)
    nodes, edges = read_ndjson(nodes_path, edges_path)
    rebuilt = merge_graph(nodes, edges)
    assert rebuilt.number_of_nodes() == graph.number_of_nodes()
    assert rebuilt.number_of_edges() == graph.number_of_edges()
