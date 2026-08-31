import json
from pathlib import Path

import networkx as nx

from cobble.file_location import NOT_ATTEMPTED, FileLocationReason, NoFileLocation
from cobble.interpreter.project.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from cobble.knowledge_graph.export import (
    _node_from_json,
    read_ndjson,
    write_ndjson,
)


def _sample_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(
        (NodeKind.PROGRAM, "COACTVW"),
        kind=NodeKind.PROGRAM,
        id="COACTVW",
        location=Path("app/cbl/COACTVW.cbl"),
        attrs={"lang": "COBOL"},
    )
    graph.add_node(
        (NodeKind.COPYBOOK, "COCOM01Y"),
        kind=NodeKind.COPYBOOK,
        id="COCOM01Y",
        location=NoFileLocation(FileLocationReason.UNRESOLVED),
        attrs={},
    )
    graph.add_edge(
        (NodeKind.PROGRAM, "COACTVW"),
        (NodeKind.COPYBOOK, "COCOM01Y"),
        kind=EdgeKind.COPY,
        attrs={"line": 42},
    )
    return graph


def _round_tripped(
    tmp_path: Path,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """The sample graph, written out and read back. Nodes and edges round-trip
    independently, so they get a test each rather than one that asserts both."""
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"
    write_ndjson(_sample_graph(), nodes_path, edges_path)
    return read_ndjson(nodes_path, edges_path)


def test_a_node_round_trips_with_its_kind_location_and_attrs(tmp_path: Path) -> None:
    nodes, _edges = _round_tripped(tmp_path)
    by_id = {node.id: node for node in nodes}

    assert len(nodes) == 2
    assert (
        by_id["COACTVW"].kind,
        by_id["COACTVW"].location,
        by_id["COACTVW"].attrs,
    ) == (NodeKind.PROGRAM, Path("app/cbl/COACTVW.cbl"), {"lang": "COBOL"})
    assert by_id["COCOM01Y"].location == NoFileLocation(FileLocationReason.UNRESOLVED)


def test_an_edge_round_trips_with_both_endpoints_its_kind_and_attrs(
    tmp_path: Path,
) -> None:
    _nodes, edges = _round_tripped(tmp_path)

    assert len(edges) == 1
    assert (
        edges[0].source,
        edges[0].source_kind,
        edges[0].target,
        edges[0].target_kind,
        edges[0].kind,
        edges[0].attrs,
    ) == (
        "COACTVW",
        NodeKind.PROGRAM,
        "COCOM01Y",
        NodeKind.COPYBOOK,
        EdgeKind.COPY,
        {"line": 42},
    )


def test_a_node_with_no_file_says_on_the_wire_why_not(tmp_path: Path) -> None:
    """The reason is what a consumer could not previously recover without
    re-deriving cobble's own resolver table from the node's kind."""
    nodes_path = tmp_path / "nodes.jsonl"
    write_ndjson(_sample_graph(), nodes_path, tmp_path / "edges.jsonl")

    rows = {
        row["id"]: row
        for row in (json.loads(line) for line in nodes_path.read_text().splitlines())
    }

    assert (rows["COCOM01Y"]["file_path"], rows["COCOM01Y"]["file_path_reason"]) == (
        None,
        "unresolved",
    )
    # Complementary: a located node carries no reason, not an empty one.
    assert (rows["COACTVW"]["file_path"], rows["COACTVW"]["file_path_reason"]) == (
        "app/cbl/COACTVW.cbl",
        None,
    )


def test_reads_a_nodes_file_written_before_reasons_existed(tmp_path: Path) -> None:
    """Every nodes.jsonl already on disk predates file_path_reason, and a corpus
    rebuild is expensive. Those rows still load — as a location that states
    nothing rather than one that invents a reason the writer never gave."""
    nodes_path = tmp_path / "nodes.jsonl"
    nodes_path.write_text(
        json.dumps({"id": "PROGONE", "kind": "PROGRAM", "file_path": None, "attrs": {}})
        + "\n"
    )
    edges_path = tmp_path / "edges.jsonl"
    edges_path.write_text("")

    nodes, _edges = read_ndjson(nodes_path, edges_path)

    assert nodes[0].location == NoFileLocation(FileLocationReason.NOT_STATED)
    assert nodes[0].location != NOT_ATTEMPTED


def test_write_ndjson_one_line_per_node_and_edge(tmp_path: Path) -> None:
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"

    write_ndjson(graph, nodes_path, edges_path)

    assert len(nodes_path.read_text().splitlines()) == 2
    assert len(edges_path.read_text().splitlines()) == 1


def test_a_node_read_back_from_the_writer_keeps_why_it_has_no_file() -> None:
    """The merge pass reads GraphWriter's own nodes.jsonl back in. It used to
    narrow every unlocated node to None there, so the reason the writer had
    just resolved and written was discarded before the merged graph saw it."""
    node = _node_from_json(
        {
            "id": "TEST.DATA",
            "kind": "DATASET",
            "file_path": None,
            "file_path_reason": "not_file_based",
            "attrs": {},
        }
    )

    assert node.location == NoFileLocation(FileLocationReason.NOT_FILE_BASED)


def test_a_node_row_with_a_path_reads_back_as_that_path() -> None:
    node = _node_from_json(
        {"id": "PROGONE", "kind": "PROGRAM", "file_path": "cbl/PROGONE.cbl"}
    )

    assert node.location == Path("cbl/PROGONE.cbl")
