"""Exact classes: fields of different programs whose every byte lands in place on each other."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from cobble.experimental.aggregates.exact_merge import exact_classes
from cobble.experimental.aggregates.unify import read_unified, write_unified
from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind


def _field(node: str, size: int, subscripts: tuple[int, ...] = ()) -> GraphNode:
    program, rest = node.split(":")
    return GraphNode(
        id=node,
        kind=NodeKind.FIELD,
        label=node,
        program=program,
        record=rest.split(".")[0],
        subscripts=subscripts,
        size=size,
    )


def _moved(ends: tuple[str, str], *placed: tuple[int, int, int]) -> GraphEdge:
    source, target = ends
    return GraphEdge(
        source=source,
        target=target,
        sites=1,
        clustered=True,
        cross_program=source.split(":")[0] != target.split(":")[0],
        barrier="none",
        alignments=tuple(
            ByteAlignment(source=s, target=t, length=n) for s, t, n in placed
        ),
        aligned=bool(placed),
    )


GRAPH = FieldGraph(
    nodes=(
        _field("R:CA.A", 2),
        _field("R:CA.C", 2),
        _field("R:CA.E", 4),
        _field("R:CA.H", 2),
        *(_field(f"S:LK.T({i})", 1, (i,)) for i in range(1, 5)),
        _field("S:WS.B", 2),
        _field("S:WS.D", 2),
        _field("S:WS.F", 2),
        _field("S:WS.G", 2),
        _field("S:WS.J", 2),
        _field("S:WS.K", 2),
        GraphNode(id="S|origin|LITERAL", kind=NodeKind.ORIGIN, label="S", program="S"),
    ),
    edges=(
        _moved(("R:CA.A", "S:LK.T(1)"), (0, 0, 1)),
        _moved(("R:CA.A", "S:LK.T(2)"), (1, 0, 1)),
        _moved(("S:LK.T(1)", "S:WS.B"), (0, 0, 1)),
        _moved(("S:LK.T(2)", "S:WS.B"), (0, 1, 1)),
        _moved(("R:CA.C", "S:LK.T(3)"), (0, 0, 1)),
        _moved(("R:CA.C", "S:LK.T(4)"), (1, 0, 1)),
        _moved(("S:LK.T(3)", "S:WS.D"), (0, 1, 1)),
        _moved(("S:LK.T(4)", "S:WS.D"), (0, 0, 1)),
        _moved(("R:CA.E", "S:WS.F"), (0, 0, 2)),
        _moved(("S:WS.B", "S:WS.G"), (0, 0, 2)),
        _moved(("R:CA.H", "S:WS.J"), (0, 0, 2)),
        _moved(("S:WS.K", "S:WS.J")),
        _moved(("S|origin|LITERAL", "S:WS.B")),
    ),
)


def test_only_fields_whose_every_byte_lands_in_place_in_another_program_are_one_class(
    tmp_path: Path,
) -> None:
    classes = exact_classes(GRAPH)
    write_unified(tmp_path / "unified.jsonl", classes)

    assert classes == (("R:CA.A", "S:WS.B"),)
    assert read_unified(tmp_path / "unified.jsonl") == {
        "R:CA.A": "R:CA.A",
        "S:WS.B": "R:CA.A",
    }


def _slot(node: str, size: int) -> GraphNode:
    return GraphNode(id=node, kind=NodeKind.DATASET, label=node, program="", size=size)


def test_fields_holding_the_same_dataset_bytes_in_two_programs_are_one_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    graph = FieldGraph(
        nodes=(
            _field("W:R.ID", 11),
            _field("R:R.ID", 11),
            _field("R:R.GRP", 5),
            _field("Q:R.ID", 11),
            _slot("DS[0:5]", 5),
            _slot("DS[5:11]", 6),
        ),
        edges=(
            _moved(("W:R.ID", "DS[0:5]"), (0, 0, 5)),
            _moved(("W:R.ID", "DS[5:11]"), (5, 0, 6)),
            _moved(("DS[0:5]", "R:R.ID"), (0, 0, 5)),
            _moved(("DS[5:11]", "R:R.ID"), (0, 5, 6)),
            _moved(("DS[0:5]", "R:R.GRP"), (0, 0, 5)),
            _moved(("DS[0:5]", "Q:R.ID")),
            _moved(("W:R.ID", "Q:R.ID"), (0, 0, 11)),
        ),
    )

    with caplog.at_level(logging.INFO):
        assert exact_classes(graph) == (("Q:R.ID", "R:R.ID", "W:R.ID"),)

    assert [record.getMessage() for record in caplog.records] == [
        *(f"aggregate unify: fields matched {n}/4" for n in range(1, 5)),
        "aggregate unify: fields matched 4/4 done",
        "aggregate unify: 2 exact pairs across programs, 1 classes",
    ]


def test_fields_reading_the_same_dataset_bytes_with_no_writer_are_one_class() -> None:
    graph = FieldGraph(
        nodes=(
            _field("A:R.ID", 5),
            _field("B:R.ID", 5),
            _field("B:R.LONG", 6),
            _slot("DS[0:5]", 5),
        ),
        edges=(
            _moved(("DS[0:5]", "A:R.ID"), (0, 0, 5)),
            _moved(("DS[0:5]", "B:R.ID"), (0, 0, 5)),
            _moved(("DS[0:5]", "B:R.LONG"), (0, 1, 5)),
        ),
    )

    assert exact_classes(graph) == (("A:R.ID", "B:R.ID"),)
