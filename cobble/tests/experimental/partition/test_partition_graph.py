"""The field graph built from extents, trace dep rows and combine links."""

from __future__ import annotations

from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange
from cobble.dataflow.fields.dep_row import DepRow
from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.extent_row import ExtentRow
from cobble.experimental.partition.fanout_barrier import FanoutBarrier
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_build import field_graph
from cobble.experimental.partition.leaf_index import leaf_index
from cobble.dataflow.combine.link_row import LinkRow
from cobble.experimental.partition.no_barrier import NoBarrier
from cobble.experimental.partition.node_kind import NodeKind


def _row(program: str, path: tuple[str, ...], *spans: tuple[int, int]) -> ExtentRow:
    region = "linkage" if program == "Q" else "working_storage"
    return ExtentRow(
        program=program,
        extents=tuple(f"{path[-1]}@{region}[{s}:{e}]" for s, e in spans),
        records=tuple(path[0] for _ in spans),
        paths=tuple(path for _ in spans),
        pics=tuple("X" for _ in spans),
        indexes=tuple((i,) if len(spans) > 1 else () for i in range(1, len(spans) + 1)),
    )


EXTENTS = (
    _row("P", ("REC",), (0, 10)),
    _row("P", ("REC", "A"), (0, 4)),
    _row("P", ("REC", "B"), (4, 10)),
    _row("P", ("OUT",), (10, 20)),
    _row("P", ("AREA",), (20, 30)),
    _row("P", ("AREA", "V1"), (20, 30)),
    _row("P", ("AREA", "V1", "X"), (20, 25)),
    _row("P", ("AREA", "V1", "Y"), (25, 30)),
    _row("P", ("AREA", "V2"), (20, 30)),
    _row("P", ("AREA", "V2", "Z"), (20, 30)),
    _row("P", ("TAB",), (30, 36)),
    _row("P", ("TAB", "T"), (30, 32), (32, 34), (34, 36)),
    _row("P", ("COPY",), (40, 50)),
    _row("P", ("COPY", "C"), (40, 44)),
    _row("P", ("COPY", "D"), (44, 50)),
    _row("P", ("ACC",), (60, 70)),
    _row("P", ("ACC", "ID"), (60, 64)),
    _row("P", ("ACC", "DATA"), (64, 70)),
    _row("P", ("SRC",), (80, 90)),
    _row("P", ("SRC", "S1"), (80, 84)),
    _row("P", ("SRC", "S2"), (84, 87)),
    _row("P", ("SRC", "S3"), (87, 90)),
    _row("Q", ("LK",), (0, 10)),
    _row("Q", ("LK", "LA"), (0, 4)),
    _row("Q", ("LK", "LB"), (4, 10)),
)


def _at(name: str, start: int, end: int) -> ByteRange:
    return ByteRange(
        program="P",
        region="working_storage",
        start=start,
        end=end,
        name=name,
        known=True,
    )


def _dep(
    target: ByteRange,
    source: ByteRange,
    site: str,
    *,
    origin: str = "",
    literal: str = "",
    sink: str = "",
    definers: tuple[str, ...] = (),
) -> DepRow:
    return DepRow(
        program="P",
        via="",
        target=target,
        origin=origin,
        literal=literal,
        source=source,
        site=site,
        definers=definers,
        sink=sink,
    )


DEPS = (
    _dep(_at("OUT", 10, 20), _at("REC", 0, 10), "s1"),
    _dep(_at("COPY", 40, 50), _at("REC", 0, 10), "s2"),
    _dep(_at("X", 20, 25), _at("A", 0, 4), "s3"),
    _dep(_at("A", 0, 4), NO_RANGE, "s4", origin="LITERAL", literal="'Y'"),
    _dep(NO_RANGE, _at("REC", 0, 10), "s5", sink="FILE:F"),
    _dep(_at("T", 32, 34), _at("A", 0, 4), "s6"),
    _dep(_at("OUT", 10, 20), _at("REC", 0, 10), "s7"),
    _dep(_at("C", 40, 44), _at("Z", 20, 30), "s8", definers=("s3",)),
    _dep(_at("OUT", 10, 20), _at("D", 44, 50), "s9", definers=("s2",)),
    _dep(NO_RANGE, _at("OUT", 10, 20), "s10", sink="FILE:G", definers=("s1",)),
    _dep(_at("ACC", 60, 70), _at("SRC", 80, 90), "s11"),
    _dep(NO_RANGE, _at("ACC", 60, 70), "s12", sink="FILE:H", definers=("s11",)),
    _dep(_at("AREA", 20, 30), NO_RANGE, "s13", origin="LITERAL", literal="SPACES"),
    _dep(_at("D", 44, 50), _at("X", 20, 25), "s14", definers=("s13",)),
)

LINKS = (
    LinkRow(
        caller="P",
        node="n1",
        callee="Q",
        caller_extent="REC@working_storage[0:10]",
        callee_extent="LK@linkage[0:10]",
        returns=True,
    ),
)


def _edges(graph: FieldGraph) -> set[tuple[str, str, int, bool]]:
    return {(e.source, e.target, e.sites, e.clustered) for e in graph.edges}


def test_moves_become_field_edges_by_the_declared_layout_and_the_writes_they_read_through_copies() -> (
    None
):
    graph = field_graph(leaf_index(EXTENTS), DEPS, LINKS, NoBarrier())

    assert {(n.id, n.kind, n.program, n.record) for n in graph.nodes} == {
        ("P:REC.A", NodeKind.FIELD, "P", "REC"),
        ("P:REC.B", NodeKind.FIELD, "P", "REC"),
        ("P:OUT.OUT", NodeKind.FIELD, "P", "OUT"),
        ("P:COPY.C", NodeKind.FIELD, "P", "COPY"),
        ("P:COPY.D", NodeKind.FIELD, "P", "COPY"),
        ("P:AREA.X", NodeKind.FIELD, "P", "AREA"),
        ("P:AREA.Y", NodeKind.FIELD, "P", "AREA"),
        ("P:AREA.Z", NodeKind.FIELD, "P", "AREA"),
        ("P:TAB.T(2)", NodeKind.FIELD, "P", "TAB"),
        ("Q:LK.LA", NodeKind.FIELD, "Q", "LK"),
        ("Q:LK.LB", NodeKind.FIELD, "Q", "LK"),
        ("P|origin|LITERAL 'Y'", NodeKind.ORIGIN, "P", ""),
        ("P|origin|LITERAL SPACES", NodeKind.ORIGIN, "P", ""),
        ("P|sink|FILE:F", NodeKind.SINK, "P", ""),
        ("P|sink|FILE:G", NodeKind.SINK, "P", ""),
        ("P:ACC.ID", NodeKind.FIELD, "P", "ACC"),
        ("P:ACC.DATA", NodeKind.FIELD, "P", "ACC"),
        ("P:SRC.S1", NodeKind.FIELD, "P", "SRC"),
        ("P:SRC.S2", NodeKind.FIELD, "P", "SRC"),
        ("P:SRC.S3", NodeKind.FIELD, "P", "SRC"),
        ("P|sink|FILE:H", NodeKind.SINK, "P", ""),
    }
    assert _edges(graph) == {
        ("P:REC.A", "P:OUT.OUT", 2, True),
        ("P:REC.B", "P:OUT.OUT", 2, True),
        ("P:REC.A", "P:COPY.C", 1, True),
        ("P:REC.B", "P:COPY.D", 1, True),
        ("P:REC.A", "P:AREA.X", 1, True),
        ("P:AREA.Z", "P:COPY.C", 1, True),
        ("P:AREA.X", "P:COPY.C", 1, True),
        ("P:COPY.D", "P:OUT.OUT", 1, True),
        ("P|origin|LITERAL 'Y'", "P:REC.A", 1, True),
        ("P|origin|LITERAL SPACES", "P:AREA.X", 1, True),
        ("P|origin|LITERAL SPACES", "P:AREA.Y", 1, True),
        ("P|origin|LITERAL SPACES", "P:AREA.Z", 1, True),
        ("P:AREA.X", "P:COPY.D", 1, True),
        ("P:REC.A", "P|sink|FILE:F", 1, True),
        ("P:REC.B", "P|sink|FILE:F", 1, True),
        ("P:REC.A", "P|sink|FILE:G", 1, True),
        ("P:REC.B", "P|sink|FILE:G", 1, True),
        ("P:SRC.S1", "P:ACC.ID", 1, True),
        ("P:SRC.S2", "P:ACC.DATA", 1, True),
        ("P:SRC.S3", "P:ACC.DATA", 1, True),
        ("P:ACC.ID", "P|sink|FILE:H", 1, True),
        ("P:SRC.S2", "P|sink|FILE:H", 1, True),
        ("P:SRC.S3", "P|sink|FILE:H", 1, True),
        ("P:REC.A", "P:TAB.T(2)", 1, True),
        ("P:REC.A", "Q:LK.LA", 1, True),
        ("P:REC.B", "Q:LK.LB", 1, True),
        ("Q:LK.LA", "P:REC.A", 1, True),
        ("Q:LK.LB", "P:REC.B", 1, True),
    }
    assert {(e.source, e.target) for e in graph.edges if e.cross_program} == {
        ("P:REC.A", "Q:LK.LA"),
        ("P:REC.B", "Q:LK.LB"),
        ("Q:LK.LA", "P:REC.A"),
        ("Q:LK.LB", "P:REC.B"),
    }
    assert {
        (e.source, e.target): (e.alignments, e.aligned)
        for e in graph.edges
        if (e.source, e.target)
        in {
            ("P:REC.A", "P:OUT.OUT"),
            ("P:REC.B", "P:OUT.OUT"),
            ("P|origin|LITERAL 'Y'", "P:REC.A"),
            ("P:REC.A", "P|sink|FILE:F"),
        }
    } == {
        ("P:REC.A", "P:OUT.OUT"): (
            (ByteAlignment(source=0, target=0, length=4),),
            True,
        ),
        ("P:REC.B", "P:OUT.OUT"): (
            (ByteAlignment(source=0, target=4, length=6),),
            True,
        ),
        ("P|origin|LITERAL 'Y'", "P:REC.A"): ((), False),
        ("P:REC.A", "P|sink|FILE:F"): ((), False),
    }
    assert graph.barrier == "none"


def test_a_fanout_barrier_keeps_wide_crossings_out_of_clustering() -> None:
    graph = field_graph(leaf_index(EXTENTS), DEPS, LINKS, FanoutBarrier(limit=1))

    assert {(s, t) for s, t, _, clustered in _edges(graph) if not clustered} == {
        ("P:REC.A", "P:OUT.OUT"),
        ("P:REC.B", "P:OUT.OUT"),
        ("P:AREA.Z", "P:COPY.C"),
        ("P:AREA.X", "P:COPY.C"),
        ("P:SRC.S1", "P:ACC.ID"),
        ("P:SRC.S2", "P:ACC.DATA"),
        ("P:SRC.S3", "P:ACC.DATA"),
    }
    assert len(graph.edges) == 28
    assert graph.barrier == "fanout-1"


def _layout(
    program: str, region: str, path: tuple[str, ...], *spans: tuple[int, int]
) -> ExtentRow:
    return ExtentRow(
        program=program,
        extents=tuple(f"{path[-1]}@{region}[{s}:{e}]" for s, e in spans),
        records=tuple(path[0] for _ in spans),
        paths=tuple(path for _ in spans),
        pics=tuple("X" for _ in spans),
        indexes=tuple((i,) if len(spans) > 1 else () for i in range(1, len(spans) + 1)),
    )


def test_a_handover_through_a_byte_table_keeps_each_occurrence_apart_and_every_byte_s_place() -> (
    None
):
    extents = (
        _layout("R", "working_storage", ("CA",), (0, 4)),
        _layout("R", "working_storage", ("CA", "CA-A"), (0, 2)),
        _layout("R", "working_storage", ("CA", "CA-B"), (2, 4)),
        _layout("S", "linkage", ("DFH",), (0, 4)),
        _layout("S", "linkage", ("DFH", "LKB"), (0, 1), (1, 2), (2, 3), (3, 4)),
        _layout("S", "working_storage", ("SA",), (0, 4)),
        _layout("S", "working_storage", ("SA", "SA-A"), (0, 2)),
        _layout("S", "working_storage", ("SA", "SA-B"), (2, 4)),
    )
    moved_in = DepRow(
        program="S",
        via="",
        target=ByteRange(
            program="S", region="working_storage", start=0, end=4, name="SA", known=True
        ),
        origin="",
        source=ByteRange(
            program="S", region="linkage", start=0, end=4, name="DFH", known=True
        ),
        site="S/m1",
        definers=(),
        sink="",
    )
    handover = LinkRow(
        caller="R",
        node="x1",
        callee="S",
        caller_extent="CA@working_storage[0:4]",
        callee_extent="DFH@linkage[0:4]",
        returns=False,
    )

    graph = field_graph(leaf_index(extents), (moved_in,), (handover,), NoBarrier())
    narrow = field_graph(
        leaf_index(extents), (moved_in,), (handover,), FanoutBarrier(limit=1)
    )

    assert {
        (n.id, n.label) for n in graph.nodes if n.program == "S" and n.record == "DFH"
    } == {
        ("S:DFH.LKB(1)", "S.LKB(1)"),
        ("S:DFH.LKB(2)", "S.LKB(2)"),
        ("S:DFH.LKB(3)", "S.LKB(3)"),
        ("S:DFH.LKB(4)", "S.LKB(4)"),
    }
    assert {(s, t) for s, t, _, _ in _edges(graph)} == {
        ("R:CA.CA-A", "S:DFH.LKB(1)"),
        ("R:CA.CA-A", "S:DFH.LKB(2)"),
        ("R:CA.CA-B", "S:DFH.LKB(3)"),
        ("R:CA.CA-B", "S:DFH.LKB(4)"),
        ("S:DFH.LKB(1)", "S:SA.SA-A"),
        ("S:DFH.LKB(2)", "S:SA.SA-A"),
        ("S:DFH.LKB(3)", "S:SA.SA-B"),
        ("S:DFH.LKB(4)", "S:SA.SA-B"),
    }
    assert {(s, t, clustered) for s, t, _, clustered in _edges(narrow)} == {
        (s, t, True) for s, t, _, _ in _edges(graph)
    }
    assert {(e.source, e.target): (e.alignments, e.aligned) for e in graph.edges} == {
        ("R:CA.CA-A", "S:DFH.LKB(1)"): (
            (ByteAlignment(source=0, target=0, length=1),),
            True,
        ),
        ("R:CA.CA-A", "S:DFH.LKB(2)"): (
            (ByteAlignment(source=1, target=0, length=1),),
            True,
        ),
        ("R:CA.CA-B", "S:DFH.LKB(3)"): (
            (ByteAlignment(source=0, target=0, length=1),),
            True,
        ),
        ("R:CA.CA-B", "S:DFH.LKB(4)"): (
            (ByteAlignment(source=1, target=0, length=1),),
            True,
        ),
        ("S:DFH.LKB(1)", "S:SA.SA-A"): (
            (ByteAlignment(source=0, target=0, length=1),),
            True,
        ),
        ("S:DFH.LKB(2)", "S:SA.SA-A"): (
            (ByteAlignment(source=0, target=1, length=1),),
            True,
        ),
        ("S:DFH.LKB(3)", "S:SA.SA-B"): (
            (ByteAlignment(source=0, target=0, length=1),),
            True,
        ),
        ("S:DFH.LKB(4)", "S:SA.SA-B"): (
            (ByteAlignment(source=0, target=1, length=1),),
            True,
        ),
    }
    assert {n.id: n.size for n in graph.nodes} == {
        "R:CA.CA-A": 2,
        "R:CA.CA-B": 2,
        "S:DFH.LKB(1)": 1,
        "S:DFH.LKB(2)": 1,
        "S:DFH.LKB(3)": 1,
        "S:DFH.LKB(4)": 1,
        "S:SA.SA-A": 2,
        "S:SA.SA-B": 2,
    }
