import json
from pathlib import Path
from unittest.mock import MagicMock

from cobble.file_location import FileLocationReason, NoFileLocation
from cobble.interpreter.project.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from cobble.knowledge_graph.graph_writer import GraphWriter


def _corpus_index_stub(
    file_paths: dict[tuple[NodeKind, str], object] | None = None,
) -> MagicMock:
    file_paths = file_paths or {}
    stub = MagicMock()
    stub.resolve_file_path.side_effect = lambda kind, node_id: file_paths.get(
        (kind, node_id), NoFileLocation(FileLocationReason.UNRESOLVED)
    )
    return stub


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_add_node_writes_immediately_no_merge_on_duplicate(tmp_path: Path) -> None:
    corpus_index = _corpus_index_stub()
    nodes_path, edges_path = tmp_path / "nodes.jsonl", tmp_path / "edges.jsonl"
    with GraphWriter(nodes_path, edges_path, corpus_index) as writer:
        writer.add_node(
            GraphNode(
                id="ACCTFILE", kind=NodeKind.PROGRAM, file_path="cbl/ACCTFILE.cbl"
            )
        )
        # A second occurrence of the same key is dropped outright, not merged —
        # its (different) file_path/attrs never win, unlike the old buffer-merge.
        writer.add_node(
            GraphNode(
                id="ACCTFILE", kind=NodeKind.PROGRAM, file_path="something/else.cbl"
            )
        )

    nodes = _read_jsonl(nodes_path)
    assert len(nodes) == 1
    assert nodes[0]["file_path"] == "cbl/ACCTFILE.cbl"


def test_add_edge_resolves_endpoint_file_path_via_corpus_index(tmp_path: Path) -> None:
    corpus_index = _corpus_index_stub(
        {(NodeKind.PROGRAM, "ACCTFILE"): Path("cbl/ACCTFILE.cbl")}
    )
    nodes_path, edges_path = tmp_path / "nodes.jsonl", tmp_path / "edges.jsonl"
    with GraphWriter(nodes_path, edges_path, corpus_index) as writer:
        writer.add_edge(
            GraphEdge(
                source="ACCTFILE",
                source_kind=NodeKind.PROGRAM,
                target="COCOM01Y",
                target_kind=NodeKind.COPYBOOK,
                kind=EdgeKind.COPY,
            )
        )

    nodes = {n["id"]: n for n in _read_jsonl(nodes_path)}
    assert nodes["ACCTFILE"]["file_path"] == "cbl/ACCTFILE.cbl"
    assert (
        nodes["COCOM01Y"]["file_path"] is None
    )  # UNRESOLVED collapses to null on write


def test_add_edge_endpoint_synthesis_never_overrides_an_explicit_add_node(
    tmp_path: Path,
) -> None:
    # Order independence: whichever occurrence of a (kind, id) is written
    # first wins, and both routes (explicit add_node, and add_edge's
    # defensive endpoint synthesis) resolve identically via corpus_index —
    # so which one happens to run first no longer matters.
    corpus_index = _corpus_index_stub(
        {(NodeKind.PROGRAM, "ACCTFILE"): Path("cbl/ACCTFILE.cbl")}
    )
    nodes_path, edges_path = tmp_path / "nodes.jsonl", tmp_path / "edges.jsonl"
    with GraphWriter(nodes_path, edges_path, corpus_index) as writer:
        writer.add_node(
            GraphNode(
                id="ACCTFILE", kind=NodeKind.PROGRAM, file_path="cbl/ACCTFILE.cbl"
            )
        )
        writer.add_edge(
            GraphEdge(
                source="ACCTFILE",
                source_kind=NodeKind.PROGRAM,
                target="COCOM01Y",
                target_kind=NodeKind.COPYBOOK,
                kind=EdgeKind.COPY,
            )
        )

    nodes = {n["id"]: n for n in _read_jsonl(nodes_path)}
    assert nodes["ACCTFILE"]["file_path"] == "cbl/ACCTFILE.cbl"


def test_edges_still_dedup_keep_first(tmp_path: Path) -> None:
    corpus_index = _corpus_index_stub()
    nodes_path, edges_path = tmp_path / "nodes.jsonl", tmp_path / "edges.jsonl"
    edge = GraphEdge(
        source="A",
        source_kind=NodeKind.PROGRAM,
        target="B",
        target_kind=NodeKind.COPYBOOK,
        kind=EdgeKind.COPY,
    )
    with GraphWriter(nodes_path, edges_path, corpus_index) as writer:
        writer.add_edge(edge)
        writer.add_edge(edge)

    assert len(_read_jsonl(edges_path)) == 1


def test_close_renames_temp_files_into_place(tmp_path: Path) -> None:
    corpus_index = _corpus_index_stub()
    nodes_path, edges_path = tmp_path / "nodes.jsonl", tmp_path / "edges.jsonl"
    with GraphWriter(nodes_path, edges_path, corpus_index) as writer:
        writer.add_node(GraphNode(id="A", kind=NodeKind.PROGRAM))

    assert nodes_path.exists()
    assert edges_path.exists()
    assert not nodes_path.with_suffix(".jsonl.tmp").exists()
