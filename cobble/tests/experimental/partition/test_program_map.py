"""The program map: one node per program and dataset record, an edge per linked pair, each program linking to its own page."""

from __future__ import annotations

from pathlib import Path

from tests.experimental.partition.graphs import LINKED, edge, program_field
from tests.experimental.partition.map_driver import drive_map
from tests.experimental.partition.map_report import MapReport

from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_index import graph_index
from cobble.experimental.partition.map_kind import MapKind
from cobble.experimental.partition.program_map import map_page, program_map
from cobble.experimental.partition.render_cli import SCRIPTS


def test_the_map_has_one_node_per_program_and_dataset_record_and_an_edge_per_linked_pair() -> (
    None
):
    graph = FieldGraph(
        nodes=(*LINKED.nodes, program_field("A#B", "X")),
        edges=(
            *LINKED.edges,
            edge("P:REC.B", "DS[0:4]", clustered=False),
            edge("A#B:REC.X", "S:REC.B", clustered=False),
        ),
    )
    drawn = program_map(graph_index(graph))

    assert [(n.id, n.kind, n.fields, n.href) for n in drawn.nodes] == [
        ("A#B", MapKind.PROGRAM, 1, "programs/A%23B.html"),
        ("DS", MapKind.DATASET, 1, ""),
        ("P", MapKind.PROGRAM, 9, "programs/P.html"),
        ("Q", MapKind.PROGRAM, 6, "programs/Q.html"),
        ("S", MapKind.PROGRAM, 2, "programs/S.html"),
    ]
    assert [(e.source, e.target, e.links) for e in drawn.edges] == [
        ("A#B", "S", 1),
        ("DS", "P", 2),
        ("DS", "Q", 1),
        ("Q", "S", 1),
    ]
    assert program_map(graph_index(graph)) == drawn


def test_the_map_page_loads_and_each_program_links_to_its_page(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    sources = tuple(f"scripts/{script.name}" for script in SCRIPTS)
    (tmp_path / sources[0]).write_bytes(SCRIPTS[0].read_bytes())
    (tmp_path / sources[1]).write_bytes(SCRIPTS[1].read_bytes())
    (tmp_path / "programs").mkdir()
    (tmp_path / "programs" / "Q.html").write_text("<p>Q</p>", "utf-8")
    out = tmp_path / "index.html"
    out.write_text(map_page(program_map(graph_index(LINKED)), sources), "utf-8")

    assert drive_map(out) == MapReport(
        errors=(),
        nodes=4,
        edges=3,
        hrefs=("programs/P.html", "programs/Q.html", "programs/S.html"),
        searched="Q",
        clicked="programs/Q.html",
    )
