import json
from pathlib import Path

import pytest
from cobble.corpus_index import FileLocationResolver
from cobble.file_location import (
    NOT_ATTEMPTED,
    FileLocation,
    FileLocationReason,
    NoFileLocation,
)
from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind
from cobble.knowledge_graph.graph_writer import graph_writer
from pydantic import ValidationError


def _lines(path: Path, *rows: dict) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_one_tagged_file_reads_back_as_its_nodes_and_its_edges(tmp_path: Path) -> None:
    graph = _lines(
        tmp_path / "graph.jsonl",
        {
            "type": "node",
            "id": "COACTVW",
            "kind": "PROGRAM",
            "file_path": "app/cbl/COACTVW.cbl",
            "file_path_reason": None,
            "attrs": {"lang": "COBOL", "nested": [1, {"a": "b"}]},
        },
        {
            "type": "edge",
            "source": "COACTVW",
            "source_kind": "PROGRAM",
            "target": "COCOM01Y",
            "target_kind": "COPYBOOK",
            "kind": "COPY",
            "attrs": {"line": 42},
        },
        {
            "type": "node",
            "id": "COCOM01Y",
            "kind": "COPYBOOK",
            "file_path": None,
            "file_path_reason": "unresolved",
            "attrs": {},
        },
    )

    nodes, edges = read_graph(graph)

    assert nodes == [
        GraphNode(
            id="COACTVW",
            kind=NodeKind.PROGRAM,
            location=Path("app/cbl/COACTVW.cbl"),
            attrs={"lang": "COBOL", "nested": [1, {"a": "b"}]},
        ),
        GraphNode(
            id="COCOM01Y",
            kind=NodeKind.COPYBOOK,
            location=NoFileLocation(FileLocationReason.UNRESOLVED),
            attrs={},
        ),
    ]
    assert edges == [
        GraphEdge(
            source="COACTVW",
            source_kind=NodeKind.PROGRAM,
            target="COCOM01Y",
            target_kind=NodeKind.COPYBOOK,
            kind=EdgeKind.COPY,
            attrs={"line": 42},
        ),
    ]


@pytest.mark.parametrize(
    "row",
    [
        {
            "id": "A",
            "kind": "PROGRAM",
            "file_path": "a.cbl",
            "file_path_reason": None,
            "attrs": {},
        },
        {
            "type": "node",
            "id": "A",
            "kind": "PROGRAM",
            "file_path": None,
            "file_path_reason": None,
            "attrs": {},
        },
    ],
    ids=["untagged", "neither-path-nor-reason"],
)
def test_a_row_the_format_does_not_admit_is_refused(tmp_path: Path, row: dict) -> None:
    with pytest.raises(ValidationError):
        read_graph(_lines(tmp_path / "graph.jsonl", row))


class _NothingResolved(FileLocationResolver):
    def resolve_file_path(self, kind: NodeKind, node_id: str) -> FileLocation:
        return NOT_ATTEMPTED


@pytest.mark.parametrize(
    "location",
    [
        Path("cbl/PROGONE.cbl"),
        *(NoFileLocation(reason) for reason in FileLocationReason),
    ],
    ids=str,
)
def test_what_the_writer_writes_the_reader_reads_back(
    tmp_path: Path, location: FileLocation
) -> None:
    """Parametrized over the enum rather than a hand-listed set, so a reason added
    later cannot be silently unwritable or unreadable."""
    node = GraphNode(
        id="PROGONE",
        kind=NodeKind.PROGRAM,
        location=location,
        attrs={"lang": "COBOL", "lines": [1, 2], "nested": {"a": [True, 1.5]}},
    )
    edge = GraphEdge(
        source="PROGONE",
        source_kind=NodeKind.PROGRAM,
        target="COCOM01Y",
        target_kind=NodeKind.COPYBOOK,
        kind=EdgeKind.COPY,
        attrs={"line": 42},
    )
    graph = tmp_path / "graph.jsonl"
    with graph_writer(graph, _NothingResolved()) as writer:
        writer.add_node(node)
        writer.add_edge(edge)

    assert read_graph(graph) == (
        [
            node,
            GraphNode(id="COCOM01Y", kind=NodeKind.COPYBOOK, location=NOT_ATTEMPTED),
        ],
        [edge],
    )
