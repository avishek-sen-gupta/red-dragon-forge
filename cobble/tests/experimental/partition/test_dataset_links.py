"""Dataset slots: every layout used on a dataset cuts its record, and fields link to the slots they cover."""

from __future__ import annotations

from cobble.dataflow.fields.extent_text import ByteRange
from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.certainty import Certainty
from cobble.experimental.partition.clustering import cluster_set
from cobble.experimental.partition.dataset_links import with_datasets
from cobble.experimental.partition.dataset_site import DatasetSite
from cobble.experimental.partition.extent_row import ExtentRow
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.file_site import FileSite
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.leaf_index import leaf_index
from cobble.experimental.partition.node_kind import NodeKind

EMPTY = FieldGraph(nodes=(), edges=())

_Edge = tuple[str, str, tuple[tuple[int, int, int], ...], Certainty, tuple[str, ...]]


def _row(program: str, path: tuple[str, ...], start: int, end: int) -> ExtentRow:
    return ExtentRow(
        program=program,
        extents=(f"{path[-1]}@working_storage[{start}:{end}]",),
        records=(path[0],),
        paths=(path,),
        pics=("X",),
        indexes=((),),
    )


INDEX = leaf_index(
    (
        _row("W", ("WREC",), 0, 11),
        _row("W", ("WREC", "ID"), 0, 11),
        _row("R", ("RREC",), 0, 14),
        _row("R", ("RREC", "GRP"), 0, 5),
        _row("R", ("RREC", "SEQ"), 5, 11),
        _row("R", ("RREC", "X"), 11, 14),
        _row("V", ("VREC",), 0, 5),
        _row("V", ("VREC", "TYPE"), 0, 1),
        _row("V", ("VREC", "V1"), 1, 5),
        _row("V", ("VREC", "V1", "A"), 1, 5),
        _row("V", ("VREC", "V2"), 1, 5),
        _row("V", ("VREC", "V2", "B"), 1, 3),
        _row("V", ("VREC", "V2", "C"), 3, 5),
    )
)


def _record(program: str, name: str, end: int, *, exact: bool = True) -> ByteRange:
    return ByteRange(
        program=program,
        region="working_storage",
        start=0,
        end=end,
        name=name,
        exact=exact,
        known=True,
    )


def _site(
    program: str,
    record: ByteRange,
    identity: str,
    *,
    writes: bool = False,
    reasons: tuple[str, ...] = (),
    resolved: bool = True,
) -> DatasetSite:
    return DatasetSite(
        FileSite(program, f"{program}/P/0", "F", record, writes),
        identity,
        Certainty.POSSIBLE if reasons else Certainty.EXACT,
        reasons,
        resolved,
    )


def _edges(graph: FieldGraph) -> set[_Edge]:
    return {
        (
            edge.source,
            edge.target,
            tuple((a.source, a.target, a.length) for a in edge.alignments),
            edge.certainty,
            edge.reasons,
        )
        for edge in graph.edges
    }


def _slots(graph: FieldGraph) -> tuple[tuple[str, int], ...]:
    return tuple(
        (node.id, node.size) for node in graph.nodes if node.kind is NodeKind.DATASET
    )


def test_writer_and_reader_layouts_are_cut_into_shared_slots() -> None:
    graph = with_datasets(
        EMPTY,
        INDEX,
        (
            _site("W", _record("W", "WREC", 11), "DS.A", writes=True),
            _site("R", _record("R", "RREC", 14), "DS.A"),
        ),
    )

    exact = Certainty.EXACT
    assert _slots(graph) == (("DS.A[0:5]", 5), ("DS.A[11:14]", 3), ("DS.A[5:11]", 6))
    assert _edges(graph) == {
        ("W:WREC.ID", "DS.A[0:5]", ((0, 0, 5),), exact, ()),
        ("W:WREC.ID", "DS.A[5:11]", ((5, 0, 6),), exact, ()),
        ("DS.A[0:5]", "R:RREC.GRP", ((0, 0, 5),), exact, ()),
        ("DS.A[5:11]", "R:RREC.SEQ", ((0, 0, 6),), exact, ()),
        ("DS.A[11:14]", "R:RREC.X", ((0, 0, 3),), exact, ()),
    }
    assert {
        (e.clustered, e.cross_program, e.aligned, e.sites) for e in graph.edges
    } == {(False, True, True, 1)}
    assert {node.id for node in graph.nodes if node.kind is NodeKind.FIELD} == {
        "W:WREC.ID",
        "R:RREC.GRP",
        "R:RREC.SEQ",
        "R:RREC.X",
    }
    assert graph.nodes[0] == GraphNode(
        id="DS.A[0:5]",
        kind=NodeKind.DATASET,
        label="DS.A[0:5]",
        program="",
        record="DS.A",
        size=5,
    )


def test_redefined_bytes_make_only_their_slots_possible() -> None:
    graph = with_datasets(EMPTY, INDEX, (_site("V", _record("V", "VREC", 5), "DS.V"),))

    layouts = ("overlapping-layouts",)
    possible = Certainty.POSSIBLE
    assert _edges(graph) == {
        ("DS.V[0:1]", "V:VREC.TYPE", ((0, 0, 1),), Certainty.EXACT, ()),
        ("DS.V[1:3]", "V:VREC.A", (), possible, layouts),
        ("DS.V[1:3]", "V:VREC.B", (), possible, layouts),
        ("DS.V[3:5]", "V:VREC.A", (), possible, layouts),
        ("DS.V[3:5]", "V:VREC.C", (), possible, layouts),
    }


def test_possible_and_unresolved_sites_get_unaligned_edges() -> None:
    graph = with_datasets(
        EMPTY,
        INDEX,
        (
            _site(
                "W",
                _record("W", "WREC", 11),
                "DS.A",
                writes=True,
                reasons=("candidates",),
            ),
            _site("R", _record("R", "RREC", 14, exact=False), "DS.B"),
            _site(
                "V",
                _record("V", "VREC", 5),
                "?LIT-X",
                reasons=("uninitialised",),
                resolved=False,
            ),
        ),
    )

    possible = Certainty.POSSIBLE
    assert ("V/P/0|?LIT-X", 5) in _slots(graph)
    assert [(n.label, n.record) for n in graph.nodes if n.id == "V/P/0|?LIT-X"] == [
        ("?LIT-X", "?LIT-X")
    ]
    assert _edges(graph) == {
        ("W:WREC.ID", "DS.A[0:11]", (), possible, ("candidates",)),
        ("DS.B[0:5]", "R:RREC.GRP", (), possible, ("clamped",)),
        ("DS.B[5:11]", "R:RREC.SEQ", (), possible, ("clamped",)),
        ("DS.B[11:14]", "R:RREC.X", (), possible, ("clamped",)),
        ("V/P/0|?LIT-X", "V:VREC.TYPE", (), possible, ("uninitialised",)),
        (
            "V/P/0|?LIT-X",
            "V:VREC.A",
            (),
            possible,
            ("uninitialised", "overlapping-layouts"),
        ),
        (
            "V/P/0|?LIT-X",
            "V:VREC.B",
            (),
            possible,
            ("uninitialised", "overlapping-layouts"),
        ),
        (
            "V/P/0|?LIT-X",
            "V:VREC.C",
            (),
            possible,
            ("uninitialised", "overlapping-layouts"),
        ),
    }


def test_dataset_edges_never_change_clusters() -> None:
    inside = FieldGraph(
        nodes=(
            GraphNode(
                id="W:WREC.ID", kind=NodeKind.FIELD, label="ID", program="W", size=11
            ),
            GraphNode(
                id="W:WS.K", kind=NodeKind.FIELD, label="K", program="W", size=11
            ),
        ),
        edges=(
            GraphEdge(
                source="W:WS.K",
                target="W:WREC.ID",
                sites=1,
                clustered=True,
                cross_program=False,
                barrier="none",
                alignments=(ByteAlignment(source=0, target=0, length=11),),
                aligned=True,
            ),
        ),
    )
    linked = with_datasets(
        inside,
        INDEX,
        (
            _site("W", _record("W", "WREC", 11), "DS.A", writes=True),
            _site("R", _record("R", "RREC", 14), "DS.A"),
        ),
    )

    assert cluster_set(linked, 30).clusters == cluster_set(inside, 30).clusters
    assert {edge.barrier for edge in linked.edges} == {"none"}


def test_a_field_straddling_the_record_start_is_aligned_from_its_own_start() -> None:
    index = leaf_index((_row("B", ("BUF",), 0, 100),))
    record = ByteRange(
        program="B", region="working_storage", start=10, end=60, name="BUF", known=True
    )
    graph = with_datasets(EMPTY, index, (_site("B", record, "DS.S", writes=True),))

    assert _edges(graph) == {
        ("B:BUF.BUF", "DS.S[0:50]", ((10, 0, 50),), Certainty.EXACT, ()),
    }
