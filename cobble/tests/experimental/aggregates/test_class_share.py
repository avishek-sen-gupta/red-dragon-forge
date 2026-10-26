"""How much of the matrix the unified classes' columns hold, per decompose threshold."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
from scipy.sparse import csr_matrix

from cobble.experimental.aggregates import class_share_cli
from cobble.experimental.aggregates.matrix import IncidenceMatrix, save_matrix
from cobble.experimental.aggregates.unify import write_unified
from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.certainty import Certainty
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_file import write_graph
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind


def _node(node: str, kind: NodeKind, size: int) -> GraphNode:
    return GraphNode(id=node, kind=kind, label=node, program=node[0], size=size)


def _edge(
    ends: tuple[str, str], length: int, certainty: Certainty = Certainty.EXACT
) -> GraphEdge:
    return GraphEdge(
        source=ends[0],
        target=ends[1],
        sites=1,
        clustered=False,
        cross_program=True,
        barrier="none",
        alignments=(
            (ByteAlignment(source=0, target=0, length=length),) if length else ()
        ),
        aligned=bool(length),
        certainty=certainty,
    )


def _main(tmp_path: Path, *thresholds: str) -> int:
    return class_share_cli.main(
        [
            "--matrix",
            str(tmp_path / "matrix.npz"),
            "--meta",
            str(tmp_path / "meta.json"),
            "--unified",
            str(tmp_path / "unified.jsonl"),
            "--graph",
            str(tmp_path / "graph.jsonl"),
            "--min-occurrences",
            *thresholds,
        ]
    )


def test_each_threshold_reports_its_columns_class_columns_and_their_share_of_entries(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    save_matrix(
        IncidenceMatrix(
            matrix=csr_matrix(
                np.array([[1, 1, 0, 0], [1, 1, 1, 0], [0, 0, 0, 1]], dtype=np.float32)
            ),
            fields=("A:R.X", "A:R.Y", "B:R.Z", "C:Q.W"),
            paragraphs=(("A", "P0"), ("A", "P1"), ("C", "P2")),
            occurrences=(2, 2, 1, 1),
        ),
        tmp_path / "matrix.npz",
        tmp_path / "meta.json",
    )
    write_unified(tmp_path / "unified.jsonl", (("A:R.X", "B:R.X"), ("B:R.Z", "D:R.Z")))

    write_graph(tmp_path / "graph.jsonl", FieldGraph(nodes=(), edges=()))

    with caplog.at_level(logging.INFO):
        assert _main(tmp_path, "2", "1") == 0

    assert [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("aggregate class share: min-occurrences")
    ] == [
        "aggregate class share: min-occurrences 2: 2 columns, 1 class columns, "
        "50.0% of their entries in class columns",
        "aggregate class share: min-occurrences 1: 4 columns, 2 class columns, "
        "50.0% of their entries in class columns",
    ]


def test_fields_a_dataset_slot_links_are_counted_by_what_kept_each_out_of_a_class(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    save_matrix(
        IncidenceMatrix(
            matrix=csr_matrix(np.array([[1]], dtype=np.float32)),
            fields=("A:R.ID",),
            paragraphs=(("A", "P0"),),
            occurrences=(1,),
        ),
        tmp_path / "matrix.npz",
        tmp_path / "meta.json",
    )
    write_unified(tmp_path / "unified.jsonl", (("A:R.ID", "B:R.ID"),))
    write_graph(
        tmp_path / "graph.jsonl",
        FieldGraph(
            nodes=(
                *(
                    _node(field, NodeKind.FIELD, 4)
                    for field in ("A:R.ID", "B:R.ID", "C:R.ID", "C:WS.X", "E:R.ID")
                ),
                _node("D:R.ID", NodeKind.FIELD, 8),
                _node("DS[0:4]", NodeKind.DATASET, 4),
            ),
            edges=(
                _edge(("A:R.ID", "DS[0:4]"), 4),
                _edge(("DS[0:4]", "B:R.ID"), 4),
                _edge(("DS[0:4]", "C:R.ID"), 4),
                _edge(("C:WS.X", "C:R.ID"), 0),
                _edge(("DS[0:4]", "D:R.ID"), 4),
                _edge(("DS[0:4]", "E:R.ID"), 0, Certainty.POSSIBLE),
            ),
        ),
    )

    with caplog.at_level(logging.INFO):
        assert _main(tmp_path, "1") == 0

    assert [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("aggregate class share: graph")
    ] == [
        "aggregate class share: graph has 6 fields, 1 dataset slots, "
        "4 exact and 1 possible dataset edges",
        "aggregate class share: graph links 4 fields to slots by exact edges: "
        "2 in a class, 1 blocked by an edge without placement, 1 neither",
        "aggregate class share: graph links 1 fields to slots only by possible edges",
    ]
