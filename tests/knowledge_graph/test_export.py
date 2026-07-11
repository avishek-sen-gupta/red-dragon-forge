from pathlib import Path

import networkx as nx

from cobble.interpreter.project.graph_types import EdgeKind, NodeKind
from cobble.knowledge_graph.export import read_ndjson, write_ndjson


def _sample_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(
        (NodeKind.PROGRAM, "COACTVW"),
        kind=NodeKind.PROGRAM, id="COACTVW",
        file_path="app/cbl/COACTVW.cbl", attrs={"lang": "COBOL"},
    )
    graph.add_node(
        (NodeKind.COPYBOOK, "COCOM01Y"),
        kind=NodeKind.COPYBOOK, id="COCOM01Y",
        file_path=None, attrs={},
    )
    graph.add_edge(
        (NodeKind.PROGRAM, "COACTVW"), (NodeKind.COPYBOOK, "COCOM01Y"),
        kind=EdgeKind.COPY, attrs={"line": 42},
    )
    return graph


def test_write_then_read_ndjson_round_trips(tmp_path: Path) -> None:
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"

    write_ndjson(graph, nodes_path, edges_path)
    nodes, edges = read_ndjson(nodes_path, edges_path)

    assert len(nodes) == 2
    assert len(edges) == 1

    by_id = {n.id: n for n in nodes}
    assert by_id["COACTVW"].kind == NodeKind.PROGRAM
    assert by_id["COACTVW"].file_path == "app/cbl/COACTVW.cbl"
    assert by_id["COACTVW"].attrs == {"lang": "COBOL"}
    assert by_id["COCOM01Y"].file_path is None

    edge = edges[0]
    assert edge.source == "COACTVW"
    assert edge.source_kind == NodeKind.PROGRAM
    assert edge.target == "COCOM01Y"
    assert edge.target_kind == NodeKind.COPYBOOK
    assert edge.kind == EdgeKind.COPY
    assert edge.attrs == {"line": 42}


def test_write_ndjson_one_line_per_node_and_edge(tmp_path: Path) -> None:
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"

    write_ndjson(graph, nodes_path, edges_path)

    assert len(nodes_path.read_text().splitlines()) == 2
    assert len(edges_path.read_text().splitlines()) == 1
