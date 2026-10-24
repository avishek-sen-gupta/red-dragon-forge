"""File sites resolved to dataset identities through the knowledge graph and the resolved file targets."""

from __future__ import annotations

from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange
from cobble.dataflow.fields.trace_query import DepRow
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.target_site import TargetSite
from cobble.experimental.partition.certainty import Certainty
from cobble.experimental.partition.dataset_resolution import dataset_sites, file_sites
from cobble.experimental.partition.dataset_site import DatasetSite
from cobble.experimental.partition.file_site import FileSite
from cobble.experimental.partition.knowledge_graph_view import KnowledgeGraph
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge, NodeKind


def _record(program: str, name: str = "REC") -> ByteRange:
    return ByteRange(
        program=program, region="file", start=0, end=10, name=name, known=True
    )


def _read(program: str, site: str, file: str) -> DepRow:
    return DepRow(
        program=program,
        via="",
        target=_record(program),
        origin=f"FILE:{file}",
        source=NO_RANGE,
        site=f"{program}/{site}",
        definers=(),
        sink="",
    )


def _write(program: str, site: str, file: str) -> DepRow:
    return DepRow(
        program=program,
        via="",
        target=NO_RANGE,
        origin="",
        source=_record(program),
        site=f"{program}/{site}",
        definers=(),
        sink=f"FILE:{file}",
    )


def _edge(
    source: tuple[str, NodeKind],
    kind: EdgeKind,
    target: tuple[str, NodeKind],
    **attrs: str,
) -> GraphEdge:
    return GraphEdge(
        source=source[0],
        source_kind=source[1],
        target=target[0],
        target_kind=target[1],
        kind=kind,
        attrs=dict(attrs),
    )


def _program(name: str) -> tuple[str, NodeKind]:
    return (name, NodeKind.PROGRAM)


def _step(name: str) -> tuple[str, NodeKind]:
    return (name, NodeKind.STEP)


def _dataset(name: str) -> tuple[str, NodeKind]:
    return (name, NodeKind.DATASET)


def _dd(name: str) -> tuple[str, NodeKind]:
    return (name, NodeKind.COBOL_FILE)


def _cics(name: str) -> tuple[str, NodeKind]:
    return (name, NodeKind.CICS_FILE)


BATCH = KnowledgeGraph(
    edges=(
        _edge(_program("W"), EdgeKind.WRITES, _dd("OUT"), select_name="OUT-FILE"),
        _edge(_step("J1.S1"), EdgeKind.JCL_STEP_RUNS, _program("W")),
        _edge(_step("J1.S1"), EdgeKind.WRITES, _dataset("DS.A"), ddname="OUT"),
        _edge(_program("R"), EdgeKind.READS, _dd("IN"), select_name="IN-FILE"),
        _edge(_program("C"), EdgeKind.CALL, _program("R")),
        _edge(_step("J2.S1"), EdgeKind.JCL_STEP_RUNS, _program("C")),
        _edge(_step("J2.S1"), EdgeKind.READS, _dataset("DS.A"), ddname="IN"),
        _edge(_program("N"), EdgeKind.READS, _dd("IN"), select_name="IN-FILE"),
        _edge(_program("M"), EdgeKind.READS, _dd("MIN"), select_name="M-FILE"),
        _edge(_step("J3.S1"), EdgeKind.JCL_STEP_RUNS, _program("M")),
        _edge(_program("K"), EdgeKind.READS, _dd("IN"), select_name="IN-FILE"),
        _edge(_program("D"), EdgeKind.CALL_CANDIDATE, _program("K")),
        _edge(_step("J4.S1"), EdgeKind.JCL_STEP_RUNS, _program("D")),
        _edge(_step("J4.S1"), EdgeKind.READS, _dataset("DS.B"), ddname="IN"),
    )
)


def _site(deps: tuple[DepRow, ...]) -> FileSite:
    (only,) = file_sites(deps)
    return only


def test_batch_sites_resolve_through_the_steps_that_run_or_call_their_program() -> None:
    w = _site((_write("W", "P/0", "OUT-FILE"),))
    r = _site((_read("R", "P/0", "IN-FILE"),))
    n = _site((_read("N", "P/0", "IN-FILE"),))
    m = _site((_read("M", "P/0", "M-FILE"),))
    k = _site((_read("K", "P/0", "IN-FILE"),))

    found = dataset_sites((w, r, n, m, k), BATCH, ())

    assert found == (
        DatasetSite(w, "DS.A", Certainty.EXACT, (), True),
        DatasetSite(r, "DS.A", Certainty.EXACT, (), True),
        DatasetSite(n, "?IN-FILE", Certainty.POSSIBLE, ("no-step",), False),
        DatasetSite(m, "?MIN", Certainty.POSSIBLE, ("dd-unbound",), False),
        DatasetSite(k, "DS.B", Certainty.POSSIBLE, ("call-candidate",), True),
    )
    assert w == FileSite("W", "W/P/0", "OUT-FILE", _record("W"), True)


CSD = KnowledgeGraph(
    edges=(
        _edge(_cics("ACCTDAT "), EdgeKind.DEFINES_DATASET, _dataset("DS.ACCT")),
        _edge(_cics("CARDDAT "), EdgeKind.DEFINES_DATASET, _dataset("DS.CARD")),
    )
)


def _target(node: str, candidates: tuple[str, ...], *reasons: str) -> TargetSite:
    return TargetSite(
        caller="O",
        node=node,
        kind=TargetKind.FILE,
        candidates=candidates,
        reasons=reasons,
    )


def test_cics_sites_resolve_through_resolved_targets_and_the_csd() -> None:
    one = _site((_read("O", "A/0", "LIT-ACCT"),))
    two = _site((_read("O", "B/0", "LIT-EITHER"),))
    walk = _site((_write("O", "C/0", "LIT-ACCT"),))
    none = _site((_read("O", "D/0", "LIT-X"),))
    undefined = _site((_read("O", "E/0", "LIT-USR"),))
    targets = (
        _target("A/0", ("ACCTDAT",)),
        _target("B/0", ("ACCTDAT", "CARDDAT")),
        _target("C/0", ("ACCTDAT",), "incomplete-walk"),
        _target("D/0", (), "uninitialised"),
        _target("E/0", ("USRSEC",)),
        TargetSite(caller="O", node="A/0", candidates=("PROGX",)),
    )

    found = dataset_sites((one, two, walk, none, undefined), CSD, targets)

    assert found == (
        DatasetSite(one, "DS.ACCT", Certainty.EXACT, (), True),
        DatasetSite(two, "DS.ACCT", Certainty.POSSIBLE, ("candidates",), True),
        DatasetSite(two, "DS.CARD", Certainty.POSSIBLE, ("candidates",), True),
        DatasetSite(walk, "DS.ACCT", Certainty.POSSIBLE, ("incomplete-walk",), True),
        DatasetSite(none, "?LIT-X", Certainty.POSSIBLE, ("uninitialised",), False),
        DatasetSite(undefined, "USRSEC", Certainty.EXACT, (), True),
    )


def test_repeated_dep_rows_are_one_site() -> None:
    assert file_sites(
        (*(_read("R", "P/0", "IN-FILE") for _ in range(5)), _write("R", "Q/0", "X"))
    ) == (
        FileSite("R", "R/P/0", "IN-FILE", _record("R"), False),
        FileSite("R", "R/Q/0", "X", _record("R"), True),
    )


def test_a_site_with_no_binding_is_unresolved_not_dropped() -> None:
    lost = _site((_read("Z", "P/0", "NOWHERE"),))

    assert dataset_sites((lost,), BATCH, ()) == (
        DatasetSite(lost, "?NOWHERE", Certainty.POSSIBLE, ("unresolved-file",), False),
    )
