"""The page: each cluster drawn as a ring, packed in rows, with its data embedded for the viewer."""

from __future__ import annotations

import json
import math

import pytest
from cobble.experimental.partition.clustering import cluster_set
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.layout import GAP, layout
from cobble.experimental.partition.node_kind import NodeKind
from cobble.experimental.partition.page import page


def _field(name: str) -> GraphNode:
    return GraphNode(
        id=f"P:REC.{name}",
        kind=NodeKind.FIELD,
        label=f"P.{name}",
        program="P",
        record="REC",
    )


def _edge(source: str, target: str, *, clustered: bool = True) -> GraphEdge:
    return GraphEdge(
        source=source,
        target=target,
        sites=2,
        clustered=clustered,
        cross_program=False,
    )


GRAPH = FieldGraph(
    barrier="fanout-8",
    nodes=(
        *(_field(name) for name in "ABCDE"),
        GraphNode(id="P|sink|MAP:M", kind=NodeKind.SINK, label="P MAP:M", program="P"),
    ),
    edges=(
        _edge("P:REC.A", "P:REC.B"),
        _edge("P:REC.B", "P:REC.C"),
        _edge("P:REC.C", "P:REC.D", clustered=False),
        _edge("P:REC.A", "P|sink|MAP:M"),
        _edge("P:REC.D", "P|sink|MAP:M"),
    ),
)


def test_clusters_are_rings_packed_in_rows_and_terminals_sit_by_their_fields() -> None:
    clusters = cluster_set(GRAPH, split_at=30)
    radius = 3 / (2 * math.pi)
    ring = 2 * radius + GAP
    row = math.sqrt(ring**2 + 2 * GAP**2)
    centre = ring / 2
    d = (GAP / 2, ring + GAP / 2)
    e = (GAP + GAP / 2, ring + GAP / 2)
    a = (centre + radius * math.cos(0), centre + radius * math.sin(0))

    assert row < ring + GAP
    assert layout(GRAPH, clusters) == {
        "P:REC.A": pytest.approx(a),
        "P:REC.B": pytest.approx(
            (
                centre + radius * math.cos(2 * math.pi / 3),
                centre + radius * math.sin(2 * math.pi / 3),
            )
        ),
        "P:REC.C": pytest.approx(
            (
                centre + radius * math.cos(4 * math.pi / 3),
                centre + radius * math.sin(4 * math.pi / 3),
            )
        ),
        "P:REC.D": pytest.approx(d),
        "P:REC.E": pytest.approx(e),
        "P|sink|MAP:M": pytest.approx(
            ((a[0] + d[0]) / 2 + GAP / 4, (a[1] + d[1]) / 2 + GAP / 4)
        ),
    }


def test_the_page_embeds_the_graph_with_each_field_s_component_and_cluster() -> None:
    clusters = cluster_set(GRAPH, split_at=30)
    html = page(GRAPH, clusters, scripts=("/*one*/", "/*two*/"))
    payload = json.loads(html.split("const DATA = ", 1)[1].split(";\n", 1)[0])

    assert html.count("<script>/*one*/</script>") == 1
    assert html.count("<script>/*two*/</script>") == 1
    assert payload["barrier"] == "fanout-8"
    assert [
        (n["id"], n["kind"], n["component"], n["cluster"], n["degree"])
        for n in payload["nodes"]
    ] == [
        ("P:REC.A", "field", 0, 0, 2),
        ("P:REC.B", "field", 0, 0, 2),
        ("P:REC.C", "field", 0, 0, 2),
        ("P:REC.D", "field", -1, -1, 2),
        ("P:REC.E", "field", -1, -1, 0),
        ("P|sink|MAP:M", "sink", -1, -1, 2),
    ]
    assert payload["edges"] == [
        {
            "source": e.source,
            "target": e.target,
            "sites": 2,
            "clustered": e.clustered,
            "cross_program": False,
        }
        for e in GRAPH.edges
    ]
