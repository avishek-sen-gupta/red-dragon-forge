"""Clusters stay inside a program and never cross an edge the barrier blocked."""

from __future__ import annotations

import logging

import pytest

from cobble.experimental.partition.cluster_report import cluster_report
from cobble.experimental.partition.clustering import cluster_set
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind


def _field(program: str, name: str, record: str = "REC") -> GraphNode:
    return GraphNode(
        id=f"{program}:{record}.{name}",
        kind=NodeKind.FIELD,
        label=f"{program}.{name}",
        program=program,
        record=record,
    )


def _edge(source: str, target: str, *, clustered: bool = True) -> GraphEdge:
    return GraphEdge(
        source=source,
        target=target,
        sites=1,
        clustered=clustered,
        cross_program=source.split(":")[0] != target.split(":")[0],
        barrier="fanout-8",
    )


ORIGIN = GraphNode(
    id="P|origin|LITERAL", kind=NodeKind.ORIGIN, label="P LITERAL", program="P"
)

GRAPH = FieldGraph(
    nodes=(
        _field("P", "A"),
        _field("P", "B"),
        _field("P", "C", record="OUT"),
        _field("P", "D"),
        _field("Q", "E"),
        ORIGIN,
    ),
    edges=(
        _edge("P:REC.A", "P:REC.B"),
        _edge("P:REC.B", "P:OUT.C"),
        _edge("P:OUT.C", "P:REC.D", clustered=False),
        _edge("P:REC.A", "Q:REC.E"),
        _edge("P|origin|LITERAL", "P:REC.D"),
        _edge("P|origin|LITERAL", "P:REC.A"),
    ),
)


def _two_cliques() -> FieldGraph:
    left = tuple(_field("P", f"L{i}") for i in range(4))
    right = tuple(_field("P", f"R{i}") for i in range(4))
    within = tuple(
        _edge(a.id, b.id)
        for side in (left, right)
        for i, a in enumerate(side)
        for b in side[i + 1 :]
    )
    return FieldGraph(
        nodes=(*left, *right),
        edges=(*within, _edge(left[0].id, right[0].id)),
    )


def test_components_are_bounded_by_program_and_by_blocked_edges(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        clusters = cluster_set(GRAPH, split_at=30)

    assert [record.getMessage() for record in caplog.records] == [
        "partition clusters: components clustered 1/1 done"
    ]

    assert [(c.id, c.component, c.program, c.members) for c in clusters.clusters] == [
        (0, 0, "P", ("P:OUT.C", "P:REC.A", "P:REC.B")),
    ]
    assert clusters.isolated == ("P:REC.D", "Q:REC.E")


def test_a_component_at_the_split_size_is_divided_into_communities() -> None:
    clusters = cluster_set(_two_cliques(), split_at=8)

    assert [(c.id, c.component, c.members) for c in clusters.clusters] == [
        (0, 0, ("P:REC.L0", "P:REC.L1", "P:REC.L2", "P:REC.L3")),
        (1, 0, ("P:REC.R0", "P:REC.R1", "P:REC.R2", "P:REC.R3")),
    ]
    assert cluster_set(_two_cliques(), split_at=9).clusters[0].members == (
        "P:REC.L0",
        "P:REC.L1",
        "P:REC.L2",
        "P:REC.L3",
        "P:REC.R0",
        "P:REC.R1",
        "P:REC.R2",
        "P:REC.R3",
    )


def test_the_report_lists_each_component_its_terminals_and_clusters() -> None:
    assert cluster_report(GRAPH, cluster_set(GRAPH, split_at=30)) == (
        "# Field partitions (barrier fanout-8)\n"
        "\n"
        "1 component of 2+ fields, 1 cluster, 2 isolated fields.\n"
        "\n"
        "## Component 0: P, 3 fields\n"
        "\n"
        "terminals: P LITERAL\n"
        "\n"
        "- cluster 0, 3 fields; records REC (2), OUT (1)\n"
        "  - P.A, P.B, P.C\n"
    )
