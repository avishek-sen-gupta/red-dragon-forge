import json
import threading
from pathlib import Path
from typing import Iterator

from cobble.interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind
from cobble.knowledge_graph.canonical_export import (
    FileSystemSynthesizer,
    _canonical_id,
    _category_for,
    _language_for,
    _process_node,
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


def test_synthesize_for_node_creates_file_and_directory_chain() -> None:
    fs = FileSystemSynthesizer()

    new_nodes = fs.synthesize_for_node("PROGRAM::CBACT01C", "vendor/carddemo/app/cbl/CBACT01C.cbl")

    ids = {n["id"] for n in new_nodes}
    assert ids == {
        "DIRECTORY::vendor",
        "DIRECTORY::vendor/carddemo",
        "DIRECTORY::vendor/carddemo/app",
        "DIRECTORY::vendor/carddemo/app/cbl",
        "FILE::vendor/carddemo/app/cbl/CBACT01C.cbl",
    }
    for n in new_nodes:
        assert n["category"] == ["FILE_SYSTEM"]
        assert n["generator"] == "cobble"

    edges = fs.drain_edges()
    edge_pairs = {(e["from_id"], e["to_id"]) for e in edges}
    assert edge_pairs == {
        ("DIRECTORY::vendor", "DIRECTORY::vendor/carddemo"),
        ("DIRECTORY::vendor/carddemo", "DIRECTORY::vendor/carddemo/app"),
        ("DIRECTORY::vendor/carddemo/app", "DIRECTORY::vendor/carddemo/app/cbl"),
        ("DIRECTORY::vendor/carddemo/app/cbl", "FILE::vendor/carddemo/app/cbl/CBACT01C.cbl"),
        ("FILE::vendor/carddemo/app/cbl/CBACT01C.cbl", "PROGRAM::CBACT01C"),
    }
    assert all(e["type"] == "MADE_OF" for e in edges)


def test_synthesize_for_node_dedups_shared_directories_and_file() -> None:
    fs = FileSystemSynthesizer()
    fs.synthesize_for_node("JOB::ACCTFILE", "vendor/carddemo/app/jcl/ACCTFILE.jcl")
    fs.drain_edges()  # discard the first call's DIRECTORY/FILE chain edges

    # A second node in the same file: only the new FILE->node edge and node
    # itself are new; the FILE/DIRECTORY chain is not re-emitted.
    new_nodes = fs.synthesize_for_node("STEP::ACCTFILE.STEP05", "vendor/carddemo/app/jcl/ACCTFILE.jcl")

    assert new_nodes == []
    edges = fs.drain_edges()
    assert edges == [{
        "from_id": "FILE::vendor/carddemo/app/jcl/ACCTFILE.jcl",
        "to_id": "STEP::ACCTFILE.STEP05",
        "type": "MADE_OF",
    }]


def test_drain_edges_clears_accumulated_edges() -> None:
    fs = FileSystemSynthesizer()
    fs.synthesize_for_node("PROGRAM::A", "a.cbl")
    assert len(fs.drain_edges()) > 0
    assert fs.drain_edges() == []


def test_synthesize_for_node_is_thread_safe_no_duplicate_nodes() -> None:
    fs = FileSystemSynthesizer()
    results: list[list[dict]] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        new_nodes = fs.synthesize_for_node(f"PROGRAM::P{i}", "shared/dir/PROG.cbl")
        with lock:
            results.append(new_nodes)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    all_new_node_ids = [n["id"] for batch in results for n in batch]
    file_node_emissions = [i for i in all_new_node_ids if i == "FILE::shared/dir/PROG.cbl"]
    assert len(file_node_emissions) == 1  # emitted exactly once across all 20 threads


def test_process_node_with_file_path_returns_node_plus_filesystem_nodes(tmp_path: Path) -> None:
    src = tmp_path / "CBACT01C.cbl"
    src.write_text("       IDENTIFICATION DIVISION.\n")
    node = GraphNode(id="CBACT01C", kind=NodeKind.PROGRAM, file_path=str(src))
    fs = FileSystemSynthesizer()

    results = _process_node(node, "carddemo", fs)

    ids = {r["id"] for r in results}
    assert "PROGRAM::CBACT01C" in ids
    assert any(r["type"] == "FILE" for r in results)
    own_node = next(r for r in results if r["id"] == "PROGRAM::CBACT01C")
    assert own_node["code"] == "       IDENTIFICATION DIVISION.\n"
    # The FILE -> node MADE_OF edge is now buffered on the synthesizer.
    edge_targets = {e["to_id"] for e in fs.drain_edges()}
    assert "PROGRAM::CBACT01C" in edge_targets


def test_process_node_without_file_path_returns_only_the_node() -> None:
    node = GraphNode(id="ACCT.MASTER", kind=NodeKind.DATASET, file_path=None)
    fs = FileSystemSynthesizer()

    results = _process_node(node, "carddemo", fs)

    assert len(results) == 1
    assert results[0]["id"] == "DATASET::ACCT.MASTER"
    assert fs.drain_edges() == []
