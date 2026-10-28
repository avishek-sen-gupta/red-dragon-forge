"""The byte copy walk: every place the bytes of one value are copied to or fed from."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.copies import Copy, CopyWalkError, copies
from cobble.experimental.partition.copies_cli import main, report
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_file import write_graph
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind

SLOT = "D[0:4]"
OTHER_SLOT = "E[0:4]"


def _field(program: str, name: str, size: int) -> GraphNode:
    return GraphNode(
        id=f"{program}:{name}",
        kind=NodeKind.FIELD,
        label=name,
        program=program,
        record="REC",
        field=name,
        size=size,
    )


def _move(
    source: str, target: str, at: tuple[int, int, int], *, rebuilt: bool = False
) -> GraphEdge:
    return GraphEdge(
        source=source,
        target=target,
        sites=1,
        clustered=True,
        cross_program=False,
        barrier="fanout-8",
        alignments=(ByteAlignment(source=at[0], target=at[1], length=at[2]),),
        aligned=True,
        rebuilt=rebuilt,
    )


GRAPH = FieldGraph(
    nodes=(
        GraphNode(id=SLOT, kind=NodeKind.DATASET, label=SLOT, program="", size=4),
        _field("P", "A", 4),
        _field("P", "A-N", 4),
        _field("P", "V2", 4),
        _field("P", "BUF", 8),
        _field("P", "IN", 4),
        _field("P", "OTHER", 4),
        _field("P", "SUM", 4),
        _field("Q", "C", 4),
        _field("Q", "D", 4),
        GraphNode(
            id=OTHER_SLOT, kind=NodeKind.DATASET, label=OTHER_SLOT, program="", size=4
        ),
        _field("R", "F", 4),
    ),
    edges=(
        _move(SLOT, "P:A", (0, 0, 4)),
        _move("P:A", "P:BUF", (0, 2, 4)),
        _move("P:BUF", "Q:C", (2, 0, 4)),
        _move("P:IN", "P:A", (0, 0, 4)),
        _move("P:OTHER", "P:BUF", (0, 2, 4)),
        _move("P:A", "P:SUM", (0, 0, 4), rebuilt=True),
        _move("P:BUF", "Q:D", (6, 0, 2)),
        _move(OTHER_SLOT, "P:IN", (0, 0, 4)),
        _move(OTHER_SLOT, "R:F", (0, 0, 4)),
    ),
)
REDEFINES = {("P", "A-N"): "A"}


def test_a_value_is_followed_byte_by_byte_through_copies_and_their_feeders() -> None:
    assert copies(GRAPH, REDEFINES, (SLOT,), 4) == (
        Copy(node=SLOT, base=0),
        Copy(node=OTHER_SLOT, base=0),
        Copy(node="P:A", base=0),
        Copy(node="P:A-N", base=0),
        Copy(node="P:BUF", base=2),
        Copy(node="P:IN", base=0),
        Copy(node="Q:C", base=0),
        Copy(node="R:F", base=0),
    )


@pytest.mark.parametrize(
    ("start", "width", "message"),
    [
        ("P:MISSING", 4, "P:MISSING is not a node of the graph"),
        ("P:A", 8, "P:A holds 4 bytes, fewer than the width 8"),
        ("P:A", 0, "the width must be at least 1 byte, not 0"),
    ],
)
def test_a_start_the_graph_lacks_or_too_small_for_the_width_is_refused(
    start: str, width: int, message: str
) -> None:
    with pytest.raises(CopyWalkError) as refused:
        copies(GRAPH, REDEFINES, (start,), width)

    assert str(refused.value) == message


def test_the_report_names_each_place_by_program_files_first() -> None:
    assert report(GRAPH, copies(GRAPH, REDEFINES, (SLOT,), 4)) == (
        "(files): D[0:4], E[0:4]",
        "P: A, A-N, BUF+2, IN",
        "Q: C",
        "R: F",
        "8 places hold all the bytes",
    )


def test_the_command_reads_redefines_from_the_extents_and_refuses_an_unknown_start(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_graph(tmp_path / "graph.jsonl", GRAPH)
    rows = (
        {"program": "P", "names": ["A-N"], "redefines": ["A"], "extents": []},
        {"program": "P", "names": ["V2"], "redefines": [""], "extents": []},
    )
    (tmp_path / "extents.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    common = (
        "--graph",
        str(tmp_path / "graph.jsonl"),
        "--extents",
        str(tmp_path / "extents.jsonl"),
        "--width",
        "4",
    )

    found = main((*common, "--start", SLOT))
    printed = capsys.readouterr().out
    refused = main((*common, "--start", "P:MISSING"))

    assert (found, refused) == (0, 2)
    assert printed.splitlines() == [
        "(files): D[0:4], E[0:4]",
        "P: A, A-N, BUF+2, IN",
        "Q: C",
        "R: F",
        "8 places hold all the bytes",
    ]
