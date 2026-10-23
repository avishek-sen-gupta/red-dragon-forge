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
        barrier="fanout-8",
    )


GRAPH = FieldGraph(
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
            "barrier": "fanout-8",
        }
        for e in GRAPH.edges
    ]


def test_linked_groups_are_packed_without_overlapping() -> None:
    chains = (("A", "B", "C", "D", "E", "F"), ("G", "H"), ("I", "J"))
    graph = FieldGraph(
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


def _occurrence(index: int) -> GraphNode:
    return GraphNode(
        id=f"S:DFH.LKB({index})",
        kind=NodeKind.FIELD,
        label=f"S.LKB({index})",
        program="S",
        record="DFH",
        pic="X",
        field="LKB",
        subscripts=(index,),
    )


def _named(record: str, name: str) -> GraphNode:
    return GraphNode(
        id=f"S:{record}.{name}",
        kind=NodeKind.FIELD,
        label=f"S.{name}",
        program="S",
        record=record,
        field=name,
    )


def test_the_page_draws_a_run_of_occurrences_with_the_same_neighbours_as_one_node() -> (
    None
):
    lanes = {1: "A", 2: "A", 3: "B", 4: "B", 6: "B"}
    graph = FieldGraph(
        nodes=(
            *(_occurrence(i) for i in lanes),
            *(
                _named(record, f"{record}-{lane}")
                for record in ("CA", "SA")
                for lane in "AB"
            ),
        ),
        edges=tuple(
            edge
            for i, lane in lanes.items()
            for edge in (
                _edge(f"S:CA.CA-{lane}", f"S:DFH.LKB({i})"),
                _edge(f"S:DFH.LKB({i})", f"S:SA.SA-{lane}"),
            )
        ),
    )
    clusters = cluster_set(graph, split_at=30)
    html = page(graph, clusters, scripts=())
    payload = json.loads(html.split("const DATA = ", 1)[1].split(";\n", 1)[0])

    assert sorted(
        (n["id"], n["label"], n["occurrences"], n["degree"])
        for n in payload["nodes"]
        if n["record"] == "DFH"
    ) == [
        ("S:DFH.LKB(1:2)", "S.LKB(1:2)", ["S.LKB(1)", "S.LKB(2)"], 2),
        ("S:DFH.LKB(3:4)", "S.LKB(3:4)", ["S.LKB(3)", "S.LKB(4)"], 2),
        ("S:DFH.LKB(6)", "S.LKB(6)", [], 2),
    ]
    assert sorted((e["source"], e["target"], e["sites"]) for e in payload["edges"]) == [
        ("S:CA.CA-A", "S:DFH.LKB(1:2)", 2),
        ("S:CA.CA-B", "S:DFH.LKB(3:4)", 2),
        ("S:CA.CA-B", "S:DFH.LKB(6)", 2),
        ("S:DFH.LKB(1:2)", "S:SA.SA-A", 2),
        ("S:DFH.LKB(3:4)", "S:SA.SA-B", 2),
        ("S:DFH.LKB(6)", "S:SA.SA-B", 2),
    ]
    placed = {member: c.id for c in clusters.clusters for member in c.members}
    assert {
        n["id"]: n["cluster"] for n in payload["nodes"] if n["record"] == "DFH"
    } == {
        "S:DFH.LKB(1:2)": placed["S:DFH.LKB(1)"],
        "S:DFH.LKB(3:4)": placed["S:DFH.LKB(3)"],
        "S:DFH.LKB(6)": placed["S:DFH.LKB(6)"],
    }
    assert placed["S:DFH.LKB(1)"] != placed["S:DFH.LKB(3)"]
