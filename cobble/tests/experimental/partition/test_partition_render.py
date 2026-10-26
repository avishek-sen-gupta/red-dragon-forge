"""The page: linked fields drawn together, everything else around them, with its data embedded for the viewer."""

from __future__ import annotations

import json
import logging
import math
from itertools import combinations
from pathlib import Path

import pytest
from tests.experimental.partition.page_driver import drive
from tests.experimental.partition.graphs import SPREAD_OUT
from tests.experimental.partition.page_report import PageReport

from cobble.experimental.partition.certainty import Certainty
from cobble.dataflow.fields.extent_text import ByteRange
from cobble.experimental.partition.dataset_links import with_datasets
from cobble.experimental.partition.dataset_site import DatasetSite
from cobble.experimental.partition.extent_row import ExtentRow
from cobble.experimental.partition.field_components import component_of
from cobble.experimental.partition.file_site import FileSite
from cobble.experimental.partition.leaf_index import leaf_index
from cobble.experimental.partition.render_cli import SCRIPTS, SOURCES
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.layout import DOT, JITTER, layout
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


def _extent(program: str, path: tuple[str, ...], start: int, end: int) -> ExtentRow:
    return ExtentRow(
        program=program,
        extents=(f"{path[-1]}@working_storage[{start}:{end}]",),
        records=(path[0],),
        paths=(path,),
        pics=("X",),
        indexes=((),),
    )


def _dataset_site(
    program: str, record: str, end: int, identity: str, *, writes: bool = False
) -> DatasetSite:
    extent = ByteRange(
        program=program,
        region="working_storage",
        start=0,
        end=end,
        name=record,
        known=True,
    )
    return DatasetSite(
        FileSite(program, f"{program}/{identity}/0", "F", extent, writes),
        identity,
        Certainty.EXACT,
        (),
        True,
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


def test_linked_fields_sit_closer_than_a_field_nothing_links_and_no_two_dots_overlap() -> (
    None
):
    points = layout(SPREAD_OUT)
    linked = [
        math.dist(points[f"P:REC.{a}"], points[f"P:REC.{b}"])
        for a, b in ("AB", "BC", "CD", "EF")
    ]
    apart = [math.dist(points["P:REC.H"], points[f"P:REC.{name}"]) for name in "ABCDEF"]
    larger = [
        points[node.id] for node in SPREAD_OUT.nodes if node.program in ("P", "Q")
    ]
    closest = min(math.dist(a, b) for a, b in combinations(larger, 2))

    assert max(linked) < sum(apart) / len(apart)
    assert closest >= 2 * DOT


@pytest.mark.xfail(
    reason="ForceAtlas2 collapses a two-field region to one spot (red-dragon-forge-liu0)",
    strict=True,
)
def test_a_two_field_region_draws_two_separate_dots() -> None:
    points = layout(SPREAD_OUT)

    assert math.dist(points["S:REC.A"], points["S:REC.B"]) >= 2 * DOT


def test_each_program_keeps_to_its_own_region_and_slots_sit_among_their_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        points = layout(SPREAD_OUT)
    logged = [record.getMessage() for record in caplog.records]
    clouds = {
        program: [
            points[node.id] for node in SPREAD_OUT.nodes if node.program == program
        ]
        for program in "PQS"
    }
    centres = {
        program: (
            sum(x for x, _ in cloud) / len(cloud),
            sum(y for _, y in cloud) / len(cloud),
        )
        for program, cloud in clouds.items()
    }
    reach = {
        program: max(math.dist(point, centres[program]) for point in cloud)
        for program, cloud in clouds.items()
    }
    middle = (
        (points["P:REC.A"][0] + points["Q:REC.A"][0]) / 2,
        (points["P:REC.A"][1] + points["Q:REC.A"][1]) / 2,
    )

    assert set(points) == {node.id for node in SPREAD_OUT.nodes}
    assert layout(SPREAD_OUT) == points
    assert {
        pair: math.dist(centres[pair[0]], centres[pair[1]])
        >= reach[pair[0]] + reach[pair[1]]
        for pair in (("P", "Q"), ("P", "S"), ("Q", "S"))
    } == {("P", "Q"): True, ("P", "S"): True, ("Q", "S"): True}
    assert math.dist(points["DS[0:4]"], middle) <= 3 * JITTER
    assert logged == [
        "partition render: programs laid out 1/3",
        "partition render: programs laid out 2/3",
        "partition render: programs laid out 3/3",
        "partition render: programs laid out 3/3 done",
    ]


def test_the_page_embeds_the_graph_with_each_field_s_component() -> None:
    html = page(GRAPH, sources=("one.js", "two.js"))
    payload = json.loads(html.split("const DATA = ", 1)[1].split(";\n", 1)[0])

    assert html.count('<script src="one.js"></script>') == 1
    assert html.count('<script src="two.js"></script>') == 1
    assert payload["barrier"] == "fanout-8"
    assert [
        (n["id"], n["kind"], n["component"], n["degree"]) for n in payload["nodes"]
    ] == [
        ("P:REC.A", "field", 0, 2),
        ("P:REC.B", "field", 0, 2),
        ("P:REC.C", "field", 0, 2),
        ("P:REC.D", "field", -1, 2),
        ("P:REC.E", "field", -1, 0),
        ("P|sink|MAP:M", "sink", -1, 2),
    ]
    assert payload["edges"] == [
        {
            "source": e.source,
            "target": e.target,
            "sites": 2,
            "clustered": e.clustered,
            "cross_program": False,
            "barrier": "fanout-8",
            "alignments": [],
            "aligned": False,
            "certainty": "exact",
            "reasons": [],
        }
        for e in GRAPH.edges
    ]


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
    html = page(graph, sources=())
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
    placed = component_of(graph)
    assert {
        n["id"]: n["component"] for n in payload["nodes"] if n["record"] == "DFH"
    } == {
        "S:DFH.LKB(1:2)": placed["S:DFH.LKB(1)"],
        "S:DFH.LKB(3:4)": placed["S:DFH.LKB(3)"],
        "S:DFH.LKB(6)": placed["S:DFH.LKB(6)"],
    }
    assert placed["S:DFH.LKB(1)"] != placed["S:DFH.LKB(3)"]


def test_the_page_embeds_dataset_slots_and_their_edge_labels() -> None:
    slotted = FieldGraph(
        nodes=(
            _field("A"),
            GraphNode(
                id="DS[0:4]", kind=NodeKind.DATASET, label="DS[0:4]", program="", size=4
            ),
            GraphNode(
                id="Q:REC.A",
                kind=NodeKind.FIELD,
                label="Q.A",
                program="Q",
                record="REC",
            ),
        ),
        edges=(
            GraphEdge(
                source="P:REC.A",
                target="DS[0:4]",
                sites=1,
                clustered=False,
                cross_program=True,
                barrier="fanout-8",
            ),
            GraphEdge(
                source="DS[0:4]",
                target="Q:REC.A",
                sites=1,
                clustered=False,
                cross_program=True,
                barrier="fanout-8",
                certainty=Certainty.POSSIBLE,
                reasons=("candidates",),
            ),
        ),
    )
    html = page(slotted, sources=())
    payload = json.loads(html.split("const DATA = ", 1)[1].split(";\n", 1)[0])

    assert sorted((n["id"], n["kind"]) for n in payload["nodes"]) == [
        ("DS[0:4]", "dataset"),
        ("P:REC.A", "field"),
        ("Q:REC.A", "field"),
    ]
    assert [
        (e["source"], e["target"], e["certainty"], e["reasons"])
        for e in payload["edges"]
    ] == [
        ("P:REC.A", "DS[0:4]", "exact", []),
        ("DS[0:4]", "Q:REC.A", "possible", ["candidates"]),
    ]


def test_the_page_follows_one_dataset_at_a_time_and_hides_dataset_links_otherwise(
    tmp_path: Path,
) -> None:
    index = leaf_index(
        (
            _extent("W", ("WREC",), 0, 11),
            _extent("W", ("WREC", "ID"), 0, 11),
            _extent("R", ("RREC",), 0, 14),
            _extent("R", ("RREC", "GRP"), 0, 5),
            _extent("R", ("RREC", "SEQ"), 5, 11),
            _extent("R", ("RREC", "X"), 11, 14),
        )
    )
    linked = with_datasets(
        GRAPH,
        index,
        (
            _dataset_site("W", "WREC", 11, "DS.A", writes=True),
            _dataset_site("R", "RREC", 14, "DS.A"),
            _dataset_site("R", "RREC", 14, "DS.B"),
        ),
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / SOURCES[0]).write_bytes(SCRIPTS[0].read_bytes())
    (tmp_path / SOURCES[1]).write_bytes(SCRIPTS[1].read_bytes())
    (tmp_path / SOURCES[2]).write_bytes(SCRIPTS[2].read_bytes())
    out = tmp_path / "page.html"
    out.write_text(page(linked, SOURCES), encoding="utf-8")

    assert drive(out) == PageReport(
        errors=(),
        dataset_edges=8,
        visible_before=0,
        visible_toggled=8,
        rows=("4 · DS.A · 2 programs", "3 · DS.B · 1 programs"),
        followed="DS.A",
        chain_datasets=("DS.A",),
        visible_after=5,
        layout=(
            ("bytes", "R", "W"),
            ("0:5", "R.GRP ←", "W.ID →"),
            ("5:11", "R.SEQ ←", "W.ID →"),
            ("11:14", "R.X ←", ""),
        ),
        others_shown=9,
        other_colours=("#e4e4e4",),
        other_edges_shown=0,
        field_click=("component", "P.A [REC] "),
        click_labels=("P MAP:M", "P.A", "P.B"),
        highlighted=3,
        isolated_click=("component", ""),
        searched="DS.A",
    )
