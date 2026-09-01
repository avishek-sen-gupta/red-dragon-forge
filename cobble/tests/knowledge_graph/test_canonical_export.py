import json
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cobble.file_location import FileLocationReason, NoFileLocation
from cobble.interpreter.project.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
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
    write_manifest,
)

_NOT_FILE_BASED = NoFileLocation(FileLocationReason.NOT_FILE_BASED)


def test_canonical_id_prefixes_with_kind() -> None:
    assert _canonical_id(NodeKind.PROGRAM, "CBEXPORT") == "PROGRAM::CBEXPORT"
    assert _canonical_id(NodeKind.JOB, "CBEXPORT") == "JOB::CBEXPORT"


def test_category_for_code_chunk_kinds() -> None:
    for kind in (
        NodeKind.PROGRAM,
        NodeKind.COBOL_FILE,
        NodeKind.COPYBOOK,
        NodeKind.BMS_MAP,
        NodeKind.JOB,
        NodeKind.STEP,
        NodeKind.TRANSACTION,
        NodeKind.INSTREAM_DATA,
    ):
        assert _category_for(kind) == ["CODE_CHUNK"]


def test_category_for_database_kinds() -> None:
    assert _category_for(NodeKind.DATASET) == ["DATABASE"]
    assert _category_for(NodeKind.CICS_FILE) == ["DATABASE"]


def test_language_for_cobol_and_jcl_kinds() -> None:
    """Over every NodeKind, so a kind added later cannot silently default to a
    language it has nothing to do with."""
    assert {kind: _language_for(kind) for kind in NodeKind} == {
        NodeKind.PROGRAM: "COBOL",
        NodeKind.COBOL_FILE: "COBOL",
        NodeKind.COPYBOOK: "COBOL",
        NodeKind.BMS_MAP: "COBOL",
        NodeKind.JOB: "JCL",
        NodeKind.STEP: "JCL",
        NodeKind.INSTREAM_DATA: "JCL",
        NodeKind.DATASET: None,
        NodeKind.TRANSACTION: None,
        NodeKind.CICS_FILE: None,
    }


def test_read_file_text_returns_contents(tmp_path: Path) -> None:
    p = tmp_path / "PROG.cbl"
    p.write_text("       IDENTIFICATION DIVISION.\n")
    assert _read_file_text(p) == "       IDENTIFICATION DIVISION.\n"


def test_read_file_text_missing_file_returns_empty_and_does_not_raise(
    tmp_path: Path,
) -> None:
    assert _read_file_text(tmp_path / "does-not-exist.cbl") == ""


def test_transform_node_with_resolved_file_path(tmp_path: Path) -> None:
    src = tmp_path / "CBACT01C.cbl"
    src.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CBACT01C.\n")
    node = GraphNode(id="CBACT01C", kind=NodeKind.PROGRAM, location=src)

    result = _transform_node(node, project_name="carddemo")

    assert result == {
        "id": "PROGRAM::CBACT01C",
        "display_name": "CBACT01C",
        "type": "PROGRAM",
        "code": "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CBACT01C.\n",
        "path": str(src),
        "language": "COBOL",
        "generator": "cobble",
        "loc": 2,
        "cyclomatic_complexity": 0,
        "category": ["CODE_CHUNK"],
        "additional_properties": {"kind": "PROGRAM", "project_name": "carddemo"},
    }


def test_transform_node_without_resolved_file_path() -> None:
    """The canonical schema has one path field and nowhere to say why a node has
    none, so a location with only a reason flattens to "" and reads no code."""
    node = GraphNode(id="ACCT.MASTER", kind=NodeKind.DATASET, location=_NOT_FILE_BASED)

    result = _transform_node(node, project_name="carddemo")

    assert result == {
        "id": "DATASET::ACCT.MASTER",
        "display_name": "ACCT.MASTER",
        "type": "DATASET",
        "code": "",
        "path": "",
        "language": None,
        "generator": "cobble",
        "loc": 0,
        "cyclomatic_complexity": 0,
        "category": ["DATABASE"],
        "additional_properties": {"kind": "DATASET", "project_name": "carddemo"},
    }


def test_transform_edge_prefixes_both_endpoints() -> None:
    edge = GraphEdge(
        source="CBACT01C",
        source_kind=NodeKind.PROGRAM,
        target="CVACT01Y",
        target_kind=NodeKind.COPYBOOK,
        kind=EdgeKind.COPY,
        attrs={"line": 42},
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
        json.dumps(
            {
                "id": "CBACT01C",
                "kind": "PROGRAM",
                "file_path": "a/CBACT01C.cbl",
                "attrs": {},
            }
        )
        + "\n"
        + json.dumps(
            {
                "id": "ACCT.MASTER",
                "kind": "DATASET",
                "file_path": None,
                "file_path_reason": "not_file_based",
                "attrs": {},
            }
        )
        + "\n"
    )

    nodes = list(_stream_nodes(nodes_path))

    assert nodes == [
        GraphNode(
            id="CBACT01C", kind=NodeKind.PROGRAM, location=Path("a/CBACT01C.cbl")
        ),
        GraphNode(id="ACCT.MASTER", kind=NodeKind.DATASET, location=_NOT_FILE_BASED),
    ]


def test_stream_nodes_is_a_generator_not_a_list(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    nodes_path.write_text(
        json.dumps({"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}})
        + "\n"
    )

    result = _stream_nodes(nodes_path)

    assert not isinstance(result, list)
    assert isinstance(result, Iterator)


def test_stream_edges_yields_graphedge_per_line(tmp_path: Path) -> None:
    edges_path = tmp_path / "edges.jsonl"
    edges_path.write_text(
        json.dumps(
            {
                "source": "CBACT01C",
                "source_kind": "PROGRAM",
                "target": "CVACT01Y",
                "target_kind": "COPYBOOK",
                "kind": "COPY",
                "attrs": {"line": 42},
            }
        )
        + "\n"
    )

    edges = list(_stream_edges(edges_path))

    assert edges == [
        GraphEdge(
            source="CBACT01C",
            source_kind=NodeKind.PROGRAM,
            target="CVACT01Y",
            target_kind=NodeKind.COPYBOOK,
            kind=EdgeKind.COPY,
            attrs={"line": 42},
        )
    ]


def test_synthesize_for_node_creates_file_and_directory_chain() -> None:
    fs = FileSystemSynthesizer()

    new_nodes = fs.synthesize_for_node(
        "PROGRAM::CBACT01C", "vendor/carddemo/app/cbl/CBACT01C.cbl"
    )

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
        (
            "DIRECTORY::vendor/carddemo/app/cbl",
            "FILE::vendor/carddemo/app/cbl/CBACT01C.cbl",
        ),
        ("FILE::vendor/carddemo/app/cbl/CBACT01C.cbl", "PROGRAM::CBACT01C"),
    }
    assert all(e["type"] == "MADE_OF" for e in edges)


def test_synthesize_for_node_dedups_shared_directories_and_file() -> None:
    fs = FileSystemSynthesizer()
    fs.synthesize_for_node("JOB::ACCTFILE", "vendor/carddemo/app/jcl/ACCTFILE.jcl")
    fs.drain_edges()  # discard the first call's DIRECTORY/FILE chain edges

    # A second node in the same file: only the new FILE->node edge and node
    # itself are new; the FILE/DIRECTORY chain is not re-emitted.
    new_nodes = fs.synthesize_for_node(
        "STEP::ACCTFILE.STEP05", "vendor/carddemo/app/jcl/ACCTFILE.jcl"
    )

    assert new_nodes == []
    edges = fs.drain_edges()
    assert edges == [
        {
            "from_id": "FILE::vendor/carddemo/app/jcl/ACCTFILE.jcl",
            "to_id": "STEP::ACCTFILE.STEP05",
            "type": "MADE_OF",
        }
    ]


def test_drain_edges_clears_accumulated_edges() -> None:
    fs = FileSystemSynthesizer()
    fs.synthesize_for_node("PROGRAM::A", "a.cbl")
    assert len(fs.drain_edges()) > 0
    assert fs.drain_edges() == []


def test_synthesize_for_node_is_thread_safe_no_duplicate_nodes() -> None:
    """Twenty nodes in one file, resolved concurrently: the FILE node is emitted
    once in total, not once per thread that happened to get there first."""
    fs = FileSystemSynthesizer()

    with ThreadPoolExecutor(max_workers=20) as pool:
        batches = list(
            pool.map(
                lambda i: fs.synthesize_for_node(
                    f"PROGRAM::P{i}", "shared/dir/PROG.cbl"
                ),
                range(20),
            )
        )

    emitted = [node["id"] for batch in batches for node in batch]

    assert emitted.count("FILE::shared/dir/PROG.cbl") == 1


def test_process_node_with_file_path_returns_node_plus_filesystem_nodes(
    tmp_path: Path,
) -> None:
    src = tmp_path / "CBACT01C.cbl"
    src.write_text("       IDENTIFICATION DIVISION.\n")
    node = GraphNode(id="CBACT01C", kind=NodeKind.PROGRAM, location=src)

    results = _process_node(node, "carddemo", FileSystemSynthesizer())

    own_node = next(r for r in results if r["id"] == "PROGRAM::CBACT01C")

    assert own_node["code"] == "       IDENTIFICATION DIVISION.\n"
    assert any(r["type"] == "FILE" for r in results)


def test_process_node_buffers_the_file_to_node_edge_on_the_synthesizer(
    tmp_path: Path,
) -> None:
    """The FILE -> node MADE_OF edge is not returned with the nodes; it is
    buffered on the synthesizer for drain_edges() to collect later."""
    src = tmp_path / "CBACT01C.cbl"
    src.write_text("       IDENTIFICATION DIVISION.\n")
    node = GraphNode(id="CBACT01C", kind=NodeKind.PROGRAM, location=src)
    fs = FileSystemSynthesizer()

    _process_node(node, "carddemo", fs)

    assert "PROGRAM::CBACT01C" in {e["to_id"] for e in fs.drain_edges()}


def test_process_node_without_file_path_returns_only_the_node() -> None:
    node = GraphNode(id="ACCT.MASTER", kind=NodeKind.DATASET, location=_NOT_FILE_BASED)
    fs = FileSystemSynthesizer()

    results = _process_node(node, "carddemo", fs)

    assert len(results) == 1
    assert results[0]["id"] == "DATASET::ACCT.MASTER"
    assert fs.drain_edges() == []


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _exported_manifest(tmp_path: Path) -> dict:
    """A program, the copybook it COPYs, and a dataset with no file — exported.

    Shared by the two tests below so each can stay one question: the node side
    of the manifest and the edge side are independent claims about this input.
    """
    cbl = tmp_path / "CBACT01C.cbl"
    cbl.write_text("       IDENTIFICATION DIVISION.\n")
    cpy = tmp_path / "CVACT01Y.cpy"
    cpy.write_text("       01 ACCT-RECORD.\n")
    _write_jsonl(
        tmp_path / "nodes.jsonl",
        [
            {"id": "CBACT01C", "kind": "PROGRAM", "file_path": str(cbl), "attrs": {}},
            {"id": "CVACT01Y", "kind": "COPYBOOK", "file_path": str(cpy), "attrs": {}},
            {"id": "ACCT.MASTER", "kind": "DATASET", "file_path": None, "attrs": {}},
        ],
    )
    _write_jsonl(
        tmp_path / "edges.jsonl",
        [
            {
                "source": "CBACT01C",
                "source_kind": "PROGRAM",
                "target": "CVACT01Y",
                "target_kind": "COPYBOOK",
                "kind": "COPY",
                "attrs": {},
            },
        ],
    )
    write_manifest(
        tmp_path / "nodes.jsonl",
        tmp_path / "edges.jsonl",
        tmp_path / "manifest.json",
        "carddemo",
        chunk_size=2,
        max_workers=2,
    )
    return json.loads((tmp_path / "manifest.json").read_text())


def test_write_manifest_produces_valid_json_with_expected_shape(tmp_path: Path) -> None:
    manifest = _exported_manifest(tmp_path)

    assert (manifest["version"], manifest["generator"]) == ("1.0", "cobble")
    assert {"PROGRAM::CBACT01C", "COPYBOOK::CVACT01Y", "DATASET::ACCT.MASTER"} <= {
        n["id"] for n in manifest["nodes"]
    }
    assert any(n["type"] == "FILE" for n in manifest["nodes"])


def test_write_manifest_carries_extractor_edges_alongside_synthesized_ones(
    tmp_path: Path,
) -> None:
    manifest = _exported_manifest(tmp_path)
    triples = {(e["from_id"], e["to_id"], e["type"]) for e in manifest["edges"]}
    made_of = {t for f, t, kind in triples if kind == "MADE_OF"}

    assert ("PROGRAM::CBACT01C", "COPYBOOK::CVACT01Y", "COPY") in triples
    # Both file-backed nodes hang off the FILE node they were extracted from.
    assert {"PROGRAM::CBACT01C", "COPYBOOK::CVACT01Y"} <= made_of


def test_write_manifest_no_duplicate_node_ids(tmp_path: Path) -> None:
    """Two nodes extracted from one file: the FILE/DIRECTORY chain is emitted
    once, not once per node that resolved to it."""
    cbl = tmp_path / "sub" / "CBACT01C.cbl"
    cbl.parent.mkdir()
    cbl.write_text("x\n")
    _write_jsonl(
        tmp_path / "nodes.jsonl",
        [
            {"id": "CBACT01C", "kind": "PROGRAM", "file_path": str(cbl), "attrs": {}},
            {"id": "CBACT01C.STEP", "kind": "STEP", "file_path": str(cbl), "attrs": {}},
        ],
    )
    (tmp_path / "edges.jsonl").write_text("")
    output_path = tmp_path / "manifest.json"

    write_manifest(
        tmp_path / "nodes.jsonl",
        tmp_path / "edges.jsonl",
        output_path,
        "carddemo",
        chunk_size=1,
        max_workers=4,
    )

    node_ids = [n["id"] for n in json.loads(output_path.read_text())["nodes"]]

    assert len(node_ids) == len(set(node_ids))


def test_write_manifest_writes_to_tmp_then_renames(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    _write_jsonl(
        nodes_path, [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}]
    )
    edges_path = tmp_path / "edges.jsonl"
    edges_path.write_text("")
    output_path = tmp_path / "manifest.json"

    write_manifest(nodes_path, edges_path, output_path, "carddemo")

    assert output_path.exists()
    assert not output_path.with_suffix(".json.tmp").exists()
