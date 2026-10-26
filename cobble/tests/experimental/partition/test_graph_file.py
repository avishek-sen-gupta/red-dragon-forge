"""The graph file: what is written reads back as slotted records, with progress every tenth of the file."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from tests.experimental.partition.graphs import SPREAD_OUT

from cobble.experimental.partition.graph_file import read_graph, write_graph


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
