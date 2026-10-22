"""The page: linked fields drawn together, everything else around them, with its data embedded for the viewer."""

from __future__ import annotations

import json
import math

import pytest

from cobble.experimental.partition.clustering import cluster_set
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.layout import GAP, SPREAD, layout
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


def test_linked_fields_share_a_disc_and_everything_else_rings_it() -> None:
    points = layout(GRAPH)
    disc = SPREAD * math.sqrt(3) + 1.0
    band = disc + 4 * GAP

    assert set(points) == {node.id for node in GRAPH.nodes}
    assert layout(GRAPH) == points
    assert {
        node: math.hypot(*points[node]) <= disc + 1e-9
        for node in ("P:REC.A", "P:REC.B", "P:REC.C")
    } == {"P:REC.A": True, "P:REC.B": True, "P:REC.C": True}
    assert {
        node: math.hypot(*points[node])
        for node in ("P:REC.D", "P:REC.E", "P|sink|MAP:M")
    } == {
        "P:REC.D": pytest.approx(band),
        "P:REC.E": pytest.approx(band),
        "P|sink|MAP:M": pytest.approx(band),
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


def test_linked_groups_are_packed_without_overlapping() -> None:
    chains = (("A", "B", "C", "D", "E", "F"), ("G", "H"), ("I", "J"))
    graph = FieldGraph(
        barrier="fanout-8",
        nodes=tuple(_field(name) for chain in chains for name in chain),
        edges=tuple(
            _edge(f"P:REC.{a}", f"P:REC.{b}")
            for chain in chains
            for a, b in zip(chain, chain[1:])
        ),
    )
    points = layout(graph)
    centres = tuple(
        (
            sum(points[f"P:REC.{name}"][0] for name in chain) / len(chain),
            sum(points[f"P:REC.{name}"][1] for name in chain) / len(chain),
        )
        for chain in chains
    )
    radii = tuple(SPREAD * math.sqrt(len(chain)) + 1.0 for chain in chains)

    assert {
        (i, j): math.dist(centres[i], centres[j]) >= radii[i] + radii[j] + GAP - 1e-2
        for i, j in ((0, 1), (0, 2), (1, 2))
    } == {(0, 1): True, (0, 2): True, (1, 2): True}
