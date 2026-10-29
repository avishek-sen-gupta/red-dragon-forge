"""The graph file: what is written reads back as slotted records, with progress every tenth of the file."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from tests.experimental.partition.graphs import SPREAD_OUT

from cobble.dataflow.fields.origin import NO_ORIGIN, Origin
from cobble.dataflow.fields.origin_kind import OriginKind
from cobble.dataflow.fields.sink import NO_SINK, Sink
from cobble.dataflow.fields.sink_kind import SinkKind
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_file import read_graph, write_graph
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind


def test_read_graph_reads_back_what_write_graph_wrote_logging_every_tenth(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "graph.jsonl"
    write_graph(path, SPREAD_OUT)
    with caplog.at_level(logging.INFO):
        read = read_graph(path)

    assert read == SPREAD_OUT
    assert (
        hasattr(read.nodes[0], "__dict__"),
        hasattr(read.edges[0], "__dict__"),
    ) == (False, False)
    assert [record.getMessage() for record in caplog.records] == [
        *(f"partition graph: lines read {n}/30" for n in range(3, 31, 3)),
        "partition graph: lines read 30/30 done",
    ]


def test_only_a_terminal_line_carries_its_origin_or_sink(tmp_path: Path) -> None:
    """A field's line has no origin or sink entry at all; reading it back gives the
    null ones, so the file pays only for the few nodes that are terminals."""
    nodes = (
        GraphNode(id="P:R.A", kind=NodeKind.FIELD, label="P.A", program="P"),
        GraphNode(
            id="P|origin|LITERAL:'Y'",
            kind=NodeKind.ORIGIN,
            label="P LITERAL:'Y'",
            program="P",
            origin=Origin(OriginKind.LITERAL, "'Y'"),
        ),
        GraphNode(
            id="P|sink|FILE:F",
            kind=NodeKind.SINK,
            label="P FILE:F",
            program="P",
            sink=Sink(SinkKind.FILE, "F"),
        ),
    )
    graph = FieldGraph(nodes=nodes, edges=())
    path = tmp_path / "graph.jsonl"
    write_graph(path, graph)

    lines = [json.loads(line)["node"] for line in path.read_text().splitlines()]
    assert [
        (line.get("origin", "absent"), line.get("sink", "absent")) for line in lines
    ] == [
        ("absent", "absent"),
        ({"kind": "LITERAL", "name": "'Y'", "unplaced": ""}, "absent"),
        ("absent", {"kind": "FILE", "name": "F"}),
    ]
    assert read_graph(path).nodes == nodes
    assert (read_graph(path).nodes[0].origin, read_graph(path).nodes[0].sink) == (
        NO_ORIGIN,
        NO_SINK,
    )
