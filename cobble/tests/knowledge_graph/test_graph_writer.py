import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import MagicMock

from cobble.file_location import FileLocation, FileLocationReason, NoFileLocation
from cobble.knowledge_graph.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from cobble.knowledge_graph.graph_writer import GraphWriter, graph_writer
from cobble.knowledge_graph.row_type import RowType

# Shared read-only default: a stub that resolves nothing wants the same empty
# lookup every time, and a mutable {} default would be one per call site.
EMPTY_LOCATIONS: Mapping[tuple[NodeKind, str], FileLocation] = MappingProxyType({})


def _corpus_index_stub(
    locations: Mapping[tuple[NodeKind, str], FileLocation] = EMPTY_LOCATIONS,
) -> MagicMock:
    stub = MagicMock()
    stub.resolve_file_path.side_effect = lambda kind, node_id: locations.get(
        (kind, node_id), NoFileLocation(FileLocationReason.UNRESOLVED)
    )
    return stub


def _tagged(path: Path, row_type: RowType) -> list[dict]:
    return [
        row
        for row in (json.loads(line) for line in path.read_text().splitlines())
        if row["type"] == row_type.value
    ]


def test_add_node_writes_immediately_no_merge_on_duplicate(tmp_path: Path) -> None:
    corpus_index = _corpus_index_stub()
    graph_path = tmp_path / "graph.jsonl"
    with graph_writer(graph_path, corpus_index) as writer:
        writer.add_node(
            GraphNode(
                id="ACCTFILE", kind=NodeKind.PROGRAM, location=Path("cbl/ACCTFILE.cbl")
            )
        )
        # A second occurrence of the same key is dropped outright, not merged —
        # its (different) location/attrs never win, unlike the old buffer-merge.
        writer.add_node(
            GraphNode(
                id="ACCTFILE",
                kind=NodeKind.PROGRAM,
                location=Path("something/else.cbl"),
            )
        )

    nodes = _tagged(graph_path, RowType.NODE)
    assert len(nodes) == 1
    assert nodes[0]["file_path"] == "cbl/ACCTFILE.cbl"


def test_add_edge_resolves_endpoint_file_path_via_corpus_index(tmp_path: Path) -> None:
    corpus_index = _corpus_index_stub(
        {(NodeKind.PROGRAM, "ACCTFILE"): Path("cbl/ACCTFILE.cbl")}
    )
    graph_path = tmp_path / "graph.jsonl"
    with graph_writer(graph_path, corpus_index) as writer:
        writer.add_edge(
            GraphEdge(
                source="ACCTFILE",
                source_kind=NodeKind.PROGRAM,
                target="COCOM01Y",
                target_kind=NodeKind.COPYBOOK,
                kind=EdgeKind.COPY,
            )
        )

    nodes = {n["id"]: n for n in _tagged(graph_path, RowType.NODE)}
    assert nodes["ACCTFILE"]["file_path"] == "cbl/ACCTFILE.cbl"
    # ...and an unresolved endpoint says which kind of "no file" that is, rather
    # than leaving a reader to re-derive it from COPYBOOK against cobble's own
    # resolver table.
    assert (nodes["COCOM01Y"]["file_path"], nodes["COCOM01Y"]["file_path_reason"]) == (
        None,
        "unresolved",
    )


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
    graph_path = tmp_path / "graph.jsonl"
    with graph_writer(graph_path, corpus_index) as writer:
        writer.add_node(
            GraphNode(
                id="ACCTFILE", kind=NodeKind.PROGRAM, location=Path("cbl/ACCTFILE.cbl")
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

    nodes = {n["id"]: n for n in _tagged(graph_path, RowType.NODE)}
    assert nodes["ACCTFILE"]["file_path"] == "cbl/ACCTFILE.cbl"


def test_edges_still_dedup_keep_first(tmp_path: Path) -> None:
    corpus_index = _corpus_index_stub()
    graph_path = tmp_path / "graph.jsonl"
    edge = GraphEdge(
        source="A",
        source_kind=NodeKind.PROGRAM,
        target="B",
        target_kind=NodeKind.COPYBOOK,
        kind=EdgeKind.COPY,
    )
    with graph_writer(graph_path, corpus_index) as writer:
        writer.add_edge(edge)
        writer.add_edge(edge)

    assert len(_tagged(graph_path, RowType.EDGE)) == 1


def test_two_flows_between_one_field_pair_are_two_edges(tmp_path: Path) -> None:
    """A FLOWS_TO's attrs are the fact, not provenance about it.

    Endpoint-only dedup kept one of these and dropped the other, so a field
    assembled from two byte ranges of the same source reported one flow -- and
    which of the two survived depended on the producer's iteration order."""
    corpus_index = _corpus_index_stub()
    graph_path = tmp_path / "graph.jsonl"
    flow = GraphEdge(
        source="PROGA.WS-SRC",
        source_kind=NodeKind.FIELD,
        target="PROGA.WS-DST",
        target_kind=NodeKind.FIELD,
        kind=EdgeKind.FLOWS_TO,
    )
    with graph_writer(graph_path, corpus_index) as writer:
        writer.add_edge(replace(flow, attrs={"source_extent": "0:4"}))
        writer.add_edge(replace(flow, attrs={"source_extent": "4:4"}))
        writer.add_edge(replace(flow, attrs={"source_extent": "0:4"}))

    assert [
        edge["attrs"]["source_extent"] for edge in _tagged(graph_path, RowType.EDGE)
    ] == [
        "0:4",
        "4:4",
    ]


def test_an_endpoint_level_kind_still_dedups_across_differing_attrs(
    tmp_path: Path,
) -> None:
    """The other kinds keep the collapse they were built on. A copybook COPYed on
    forty lines is one fact, and attrs-level identity would turn the corpus graph
    into one edge per occurrence."""
    corpus_index = _corpus_index_stub()
    graph_path = tmp_path / "graph.jsonl"
    copy = GraphEdge(
        source="A",
        source_kind=NodeKind.PROGRAM,
        target="B",
        target_kind=NodeKind.COPYBOOK,
        kind=EdgeKind.COPY,
    )
    with graph_writer(graph_path, corpus_index) as writer:
        writer.add_edge(replace(copy, attrs={"line": 12}))
        writer.add_edge(replace(copy, attrs={"line": 40}))

    assert [edge["attrs"] for edge in _tagged(graph_path, RowType.EDGE)] == [
        {"line": 12}
    ]


def test_attrs_written_in_a_different_order_are_one_edge(tmp_path: Path) -> None:
    """Identity is the attrs, not the dict's insertion order -- which belongs to
    whichever producer built it, not to the fact."""
    corpus_index = _corpus_index_stub()
    graph_path = tmp_path / "graph.jsonl"
    flow = GraphEdge(
        source="PROGA.WS-SRC",
        source_kind=NodeKind.FIELD,
        target="PROGA.WS-DST",
        target_kind=NodeKind.FIELD,
        kind=EdgeKind.FLOWS_TO,
    )
    with graph_writer(graph_path, corpus_index) as writer:
        writer.add_edge(
            replace(flow, attrs={"node": "MAIN/0", "source_node": "MAIN/1"})
        )
        writer.add_edge(
            replace(flow, attrs={"source_node": "MAIN/1", "node": "MAIN/0"})
        )

    assert len(_tagged(graph_path, RowType.EDGE)) == 1


def test_an_edge_follows_its_endpoints_and_the_file_appears_only_on_close(
    tmp_path: Path,
) -> None:
    graph_path = tmp_path / "graph.jsonl"
    writer = GraphWriter(graph_path, _corpus_index_stub())
    writer.add_edge(
        GraphEdge(
            source="A",
            source_kind=NodeKind.PROGRAM,
            target="B",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        )
    )
    assert not graph_path.exists()
    writer.close()

    rows = [json.loads(line) for line in graph_path.read_text().splitlines()]
    assert [(row["type"], row.get("id", row.get("kind"))) for row in rows] == [
        ("node", "A"),
        ("node", "B"),
        ("edge", "CALL"),
    ]
    assert not graph_path.with_suffix(".jsonl.tmp").exists()
