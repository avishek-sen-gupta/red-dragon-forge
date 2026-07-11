import json
from pathlib import Path
from typing import Iterator

from cobble.interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind
from cobble.knowledge_graph.canonical_export import (
    _canonical_id,
    _category_for,
    _language_for,
    _read_file_text,
    _stream_edges,
    _stream_nodes,
    _transform_edge,
    _transform_node,
)


def test_canonical_id_prefixes_with_kind() -> None:
    assert _canonical_id(NodeKind.PROGRAM, "CBEXPORT") == "PROGRAM::CBEXPORT"
    assert _canonical_id(NodeKind.JOB, "CBEXPORT") == "JOB::CBEXPORT"


def test_category_for_code_chunk_kinds() -> None:
    for kind in (
        NodeKind.PROGRAM, NodeKind.COBOL_FILE, NodeKind.COPYBOOK, NodeKind.BMS_MAP,
        NodeKind.JOB, NodeKind.STEP, NodeKind.TRANSACTION, NodeKind.INSTREAM_DATA,
    ):
        assert _category_for(kind) == ["CODE_CHUNK"]


def test_category_for_database_kinds() -> None:
    assert _category_for(NodeKind.DATASET) == ["DATABASE"]
    assert _category_for(NodeKind.CICS_FILE) == ["DATABASE"]


def test_language_for_cobol_and_jcl_kinds() -> None:
    assert _language_for(NodeKind.PROGRAM) == "COBOL"
    assert _language_for(NodeKind.COBOL_FILE) == "COBOL"
    assert _language_for(NodeKind.COPYBOOK) == "COBOL"
    assert _language_for(NodeKind.BMS_MAP) == "COBOL"
    assert _language_for(NodeKind.JOB) == "JCL"
    assert _language_for(NodeKind.STEP) == "JCL"
    assert _language_for(NodeKind.INSTREAM_DATA) == "JCL"
    assert _language_for(NodeKind.DATASET) is None
    assert _language_for(NodeKind.TRANSACTION) is None
    assert _language_for(NodeKind.CICS_FILE) is None


def test_read_file_text_returns_contents(tmp_path: Path) -> None:
    p = tmp_path / "PROG.cbl"
    p.write_text("       IDENTIFICATION DIVISION.\n")
    assert _read_file_text(p) == "       IDENTIFICATION DIVISION.\n"


def test_read_file_text_missing_file_returns_empty_and_does_not_raise(tmp_path: Path) -> None:
    assert _read_file_text(tmp_path / "does-not-exist.cbl") == ""


def test_transform_node_with_resolved_file_path(tmp_path: Path) -> None:
    src = tmp_path / "CBACT01C.cbl"
    src.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CBACT01C.\n")
    node = GraphNode(id="CBACT01C", kind=NodeKind.PROGRAM, file_path=str(src))

    result = _transform_node(node, project_name="carddemo")

    assert result["id"] == "PROGRAM::CBACT01C"
    assert result["display_name"] == "CBACT01C"
    assert result["type"] == "PROGRAM"
    assert result["path"] == str(src)
    assert result["generator"] == "cobble"
    assert result["language"] == "COBOL"
    assert result["category"] == ["CODE_CHUNK"]
    assert result["code"] == "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CBACT01C.\n"
    assert result["loc"] == 2
    assert result["cyclomatic_complexity"] == 0
    assert result["additional_properties"]["project_name"] == "carddemo"
    assert result["additional_properties"]["kind"] == "PROGRAM"


def test_transform_node_without_resolved_file_path() -> None:
    node = GraphNode(id="ACCT.MASTER", kind=NodeKind.DATASET, file_path=None)

    result = _transform_node(node, project_name="carddemo")

    assert result["id"] == "DATASET::ACCT.MASTER"
    assert result["path"] == ""
    assert result["code"] == ""
    assert result["loc"] == 0
    assert result["category"] == ["DATABASE"]
    assert result["language"] is None


def test_transform_edge_prefixes_both_endpoints() -> None:
    edge = GraphEdge(
        source="CBACT01C", source_kind=NodeKind.PROGRAM,
        target="CVACT01Y", target_kind=NodeKind.COPYBOOK,
        kind=EdgeKind.COPY, attrs={"line": 42},
    )

    result = _transform_edge(edge)

    assert result == {
        "from_id": "PROGRAM::CBACT01C",
        "to_id": "COPYBOOK::CVACT01Y",
        "type": "COPY",
    }


def test_stream_nodes_yields_graphnode_per_line(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    nodes_path.write_text(
        json.dumps({"id": "CBACT01C", "kind": "PROGRAM", "file_path": "a/CBACT01C.cbl", "attrs": {}}) + "\n"
        + json.dumps({"id": "ACCT.MASTER", "kind": "DATASET", "file_path": None, "attrs": {}}) + "\n"
    )

    nodes = list(_stream_nodes(nodes_path))

    assert nodes == [
        GraphNode(id="CBACT01C", kind=NodeKind.PROGRAM, file_path="a/CBACT01C.cbl"),
        GraphNode(id="ACCT.MASTER", kind=NodeKind.DATASET, file_path=None),
    ]


def test_stream_nodes_is_a_generator_not_a_list(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    nodes_path.write_text(json.dumps({"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}) + "\n")

    result = _stream_nodes(nodes_path)

    assert not isinstance(result, list)
    assert isinstance(result, Iterator)


def test_stream_edges_yields_graphedge_per_line(tmp_path: Path) -> None:
    edges_path = tmp_path / "edges.jsonl"
    edges_path.write_text(
        json.dumps({
            "source": "CBACT01C", "source_kind": "PROGRAM",
            "target": "CVACT01Y", "target_kind": "COPYBOOK",
            "kind": "COPY", "attrs": {"line": 42},
        }) + "\n"
    )

    edges = list(_stream_edges(edges_path))

    assert edges == [
        GraphEdge(
            source="CBACT01C", source_kind=NodeKind.PROGRAM,
            target="CVACT01Y", target_kind=NodeKind.COPYBOOK,
            kind=EdgeKind.COPY, attrs={"line": 42},
        )
    ]
