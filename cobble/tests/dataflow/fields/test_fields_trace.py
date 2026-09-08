"""The path walk: its stack rules on graphs built here, its crossing on a real parse.

Two halves, because they fail for different reasons. The stack rules -- unroll a
loop once, let a paragraph PERFORMed twice run twice, take only your own RETURN
edge -- are decided by the walk alone, so they are asserted against CFGs written
out in this file where every node id is chosen here. The crossing is decided by
the bridge's layout arithmetic, which no hand-built extent can stand in for: a
rebase that is off by a byte agrees with a fixture and disagrees with COBOL.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import pytest
from cobble.dataflow.fields.side_tables import CommareaAlias
from cobble.dataflow.fields.state import Source, write
from cobble.dataflow.fields.trace import (
    NO_WINDOW,
    RE_ENTRY,
    Budget,
    DeadEnd,
    Loaded,
    Trace,
    _extent_at,
    _loaded,
    _rebased,
    _seeded,
    _window,
    loadable,
    sampled,
    traced,
    visited_order,
)
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId


def _extent(region: RegionId, start: int, length: int, name: str) -> FieldExtent:
    return FieldExtent(
        region=region,
        start=start,
        length=length,
        precision=Precision.EXACT,
        field_name=name,
    )


def _sourced(name: str, node: str) -> frozenset[Source]:
    return frozenset(
        {
            Source(
                origin="",
                extent=_extent(RegionId.WORKING_STORAGE, 0, 4, name),
                node=node,
            )
        }
    )


def test_the_region_text_round_trips_through_the_enum_that_wrote_it():
    """``FieldExtent.__str__`` spells the region as the enum's own value, so
    ``RegionId(text)`` is the way back and no mapping table is needed."""
    found = _extent_at("WS-AREA@working_storage[8:20]")

    assert found.region is RegionId.WORKING_STORAGE
    assert (found.start, found.length) == (8, 12)
    assert found.field_name == "WS-AREA"
    assert found.precision is Precision.EXACT


def test_a_text_that_is_not_an_extent_parses_to_a_length_of_nothing():
    """A dead-end alias row carries a reason where the extents would be. Zero
    length is what makes that safe to carry in an extent-shaped slot: may_alias
    and must_cover both reject a non-positive length."""
    assert not _extent_at("").length
    assert not _extent_at("callee-not-in-cache").length


def test_a_row_carrying_a_reason_yields_no_window():
    row = CommareaAlias(
        caller="TPROGA", node="MAIN-PARA/2", transfer="LINK", reason="dynamic-target"
    )

    assert _window(row, "") == NO_WINDOW


def test_a_row_carrying_both_layouts_yields_the_window_they_share():
    row = CommareaAlias(
        caller="TPROGA",
        node="MAIN-PARA/2",
        transfer="LINK",
        callee="TPROGB",
        caller_extent="WS-AREA@working_storage[8:20]",
        callee_extent="DFHCOMMAREA@linkage[0:12]",
        returns=True,
    )
    found = _window(row, "TPROGB")

    assert found.known
    assert found.caller == "TPROGA"
    assert found.caller_extent.start == 8
    assert found.callee_extent.region is RegionId.LINKAGE
    assert found.caller_extent.length == found.callee_extent.length


def test_a_rebase_shifts_by_the_two_windows_offsets_and_renames_the_bytes():
    """Caller byte ``source.start + k`` IS callee byte ``target.start + k``. The
    rebased extent takes the target record's name, because spelling the caller's
    field name inside the callee's region names a field that is not there."""
    window_in = _extent(RegionId.WORKING_STORAGE, 8, 12, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 12, "DFHCOMMAREA")
    found = _rebased(
        _extent(RegionId.WORKING_STORAGE, 12, 4, "WS-B"), window_in, window_out
    )

    assert found.region is RegionId.LINKAGE
    assert (found.start, found.length) == (4, 4)
    assert found.field_name == "DFHCOMMAREA"


def test_a_rebase_clips_to_the_window_rather_than_claiming_past_it():
    """Bytes outside the shared window are not shared storage. A rebase that kept
    them would report the callee as addressing the caller's whole record."""
    window_in = _extent(RegionId.WORKING_STORAGE, 8, 8, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 8, "DFHCOMMAREA")
    found = _rebased(
        _extent(RegionId.WORKING_STORAGE, 4, 12, "WS-WIDE"), window_in, window_out
    )

    assert (found.start, found.length) == (0, 8)


def test_seeding_carries_provenance_across_unchanged_and_credits_no_node():
    """A binding, not a flow: nothing converts and nothing pads, so the sources
    cross intact and no node is recorded as having written them."""
    window_in = _extent(RegionId.WORKING_STORAGE, 0, 8, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 8, "DFHCOMMAREA")
    held = write(
        {},
        _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-KEY"),
        _sourced("WS-SEED", "TPROGA/MAIN-PARA/0"),
    )
    found = _seeded(held, window_in, window_out)

    ((extent, sources),) = tuple(found.items())
    assert extent.region is RegionId.LINKAGE
    assert (extent.start, extent.length) == (0, 4)
    assert tuple(one.node for one in sources) == ("TPROGA/MAIN-PARA/0",)


def test_seeding_leaves_behind_whatever_the_window_does_not_reach():
    """Only the shared bytes are bound. Storage outside the commarea is the
    caller's alone and has no address in the callee at all."""
    window_in = _extent(RegionId.WORKING_STORAGE, 0, 8, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 8, "DFHCOMMAREA")
    held = write(
        {},
        _extent(RegionId.WORKING_STORAGE, 40, 4, "WS-PRIVATE"),
        _sourced("WS-SEED", "TPROGA/MAIN-PARA/0"),
    )

    assert not _seeded(held, window_in, window_out)


def test_two_caller_extents_clipping_to_one_window_range_keep_both_provenances():
    """A union, not a dict comprehension. Two extents can clip to the same shared
    range -- a record and a redefinition of it -- and keying a comprehension on the
    rebased extent would drop one of them silently."""
    window_in = _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-AREA")
    window_out = _extent(RegionId.LINKAGE, 0, 4, "DFHCOMMAREA")
    first = write(
        {},
        _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-KEY"),
        _sourced("WS-SEED", "TPROGA/MAIN-PARA/0"),
    )
    both = {
        **first,
        _extent(RegionId.WORKING_STORAGE, 0, 4, "WS-ALIAS"): _sourced(
            "WS-OTHER", "TPROGA/MAIN-PARA/1"
        ),
    }
    found = _seeded(both, window_in, window_out)

    ((_extent_out, sources),) = tuple(found.items())
    assert {one.node for one in sources} == {
        "TPROGA/MAIN-PARA/0",
        "TPROGA/MAIN-PARA/1",
    }


def _node(node_id: str, kind: NodeKind = NodeKind.NOP) -> Node:
    return Node(id=node_id, kind=kind, paragraph=node_id.split("/")[0])


def _edge(source: str, target: str, kind: EdgeKind = EdgeKind.FLOW) -> Edge:
    return Edge(source=source, target=target, kind=kind)


def _loader(*programs: Loaded):
    """A loader over programs written out here, which is the seam that lets the
    stack rules be asserted without a parse."""
    held = {one.program: one for one in programs}
    return lambda program: held[program]


def _only(program: str, nodes, edges, entry: str) -> Loaded:
    return Loaded(
        program=program,
        cfg=Cfg(program=program, nodes=tuple(nodes), edges=tuple(edges)),
        entry=entry,
    )


def _branch_edges(cfg: Cfg) -> tuple[tuple[str, str, str], ...]:
    tests = frozenset(node.id for node in cfg.nodes if node.kind is NodeKind.TEST)
    return tuple(
        (cfg.program, edge.source, edge.kind.value)
        for edge in cfg.edges
        if edge.source in tests
    )


LOOP = _only(
    "TPROGA",
    (
        _node("P/0"),
        _node("P/1", NodeKind.TEST),
        _node("P/2"),
        _node("P/3"),
    ),
    (
        _edge("P/0", "P/1"),
        _edge("P/1", "P/2", EdgeKind.TRUE),
        _edge("P/1", "P/3", EdgeKind.FALSE),
        _edge("P/2", "P/1"),
    ),
    "P/0",
)
"""A test with a body that loops back to it and an exit that does not."""


def test_a_loop_body_runs_once_and_then_the_walk_leaves():
    """The back edge targets a node the open frame has already run, so it is
    refused: the body runs once and the exit edge is taken. That is the
    unroll-once decision, and it is the same rule that stops a recursive PERFORM.
    """
    found = traced("TPROGA", _loader(LOOP), Budget(paths=1, coverage=1.0))

    assert found.paths == 1
    assert found.coverage.total == 2

    order = visited_order("TPROGA", _loader(LOOP), Budget(paths=1))
    assert order.count("P/2") == 1
    assert order == ("P/0", "P/1", "P/2")


def test_sampling_takes_a_different_arm_on_the_next_path_and_reaches_full_coverage():
    """The cursor is per (program, node) and global to the run, so path 1 takes a
    test's first arm and path 2 its second. Deterministic and reproducible, which
    is why no random seed appears anywhere in this walk.
    """
    found = traced("TPROGA", _loader(LOOP), Budget(paths=8))

    assert found.coverage.taken == {
        ("TPROGA", "P/1", "TRUE"),
        ("TPROGA", "P/1", "FALSE"),
    }
    assert found.coverage.fraction == 1.0


def test_sampling_stops_as_soon_as_the_coverage_target_is_met():
    """Both arms of the one test are taken by the second path, so a target of 1.0
    is met there and the remaining budget goes unspent."""
    found = traced("TPROGA", _loader(LOOP), Budget(paths=50, coverage=1.0))

    assert found.paths == 2


def test_a_lower_coverage_target_stops_earlier_still():
    found = traced("TPROGA", _loader(LOOP), Budget(paths=50, coverage=0.5))

    assert found.paths == 1


TWICE = _only(
    "TPROGA",
    (
        _node("M/0", NodeKind.CALL),
        _node("M/1", NodeKind.CALL),
        _node("M/2"),
        _node("S/0"),
        _node("S/end"),
    ),
    (
        _edge("M/0", "M/1"),
        _edge("M/0", "S/0", EdgeKind.PERFORM),
        _edge("M/1", "M/2"),
        _edge("M/1", "S/0", EdgeKind.PERFORM),
        _edge("S/0", "S/end"),
        _edge("S/end", "M/1", EdgeKind.RETURN),
        _edge("S/end", "M/2", EdgeKind.RETURN),
    ),
    "M/0",
)
"""Two PERFORMs of one paragraph, so ``build.py`` gave it two RETURN edges."""


def test_a_paragraph_performed_twice_in_one_path_runs_both_times():
    """Its frame took its visited nodes with it when it returned, so the second
    PERFORM starts clean. Two arms of one paragraph in one trace is real: the two
    sites genuinely can behave differently.
    """
    found = traced("TPROGA", _loader(TWICE), Budget(paths=1))

    assert found.paths == 1
    assert not found.dead_ends

    order = visited_order("TPROGA", _loader(TWICE), Budget(paths=1))
    assert order.count("S/0") == 2
    assert order.count("S/end") == 2


def test_only_the_return_edge_back_to_your_own_caller_is_taken():
    """The precision the fixpoint cannot have. ``build.py`` calls two RETURN edges
    from one paragraph "the deliberate imprecision"; a stack knows which is yours.

    Asserted by the node order, which ``Trace`` cannot give: it is the union over
    paths, so the route is exactly what it discards. Taking the wrong RETURN edge
    from the first PERFORM would skip M/1, and the second PERFORM's own return
    would never run.
    """
    assert visited_order("TPROGA", _loader(TWICE), Budget(paths=1)) == (
        "M/0",
        "S/0",
        "S/end",
        "M/1",
        "S/0",
        "S/end",
        "M/2",
    )


FALLEN = _only(
    "TPROGA",
    (_node("M/0"), _node("M/end"), _node("S/0"), _node("S/end")),
    (
        _edge("M/0", "M/end"),
        _edge("M/0", "S/0", EdgeKind.PERFORM),
        _edge("M/end", "S/0", EdgeKind.FALLTHRU),
        _edge("S/0", "S/end"),
        _edge("S/end", "M/end", EdgeKind.RETURN),
    ),
    "M/0",
)
"""A paragraph both PERFORMed and fallen into, which is the shape that makes a
RETURN edge wrong: reached by falling through, its caller's resume point is none
of its business."""


def test_a_paragraph_fallen_into_rather_than_performed_takes_no_return_edge():
    """No frame's resume point matches, so every RETURN edge is dropped and the
    path ends where the paragraph does -- rather than jumping to a caller that is
    not on the stack."""
    assert visited_order("TPROGA", _loader(FALLEN), Budget(paths=1)) == (
        "M/0",
        "S/0",
        "S/end",
        "M/end",
        "S/0",
        "S/end",
    )


def test_coverage_counts_branch_edges_and_not_every_edge_walked():
    """A TEST has exactly two out-edges and everything else has one route through
    it, so counting the rest would make the percentage a node count wearing a
    branch's name."""
    found = traced("TPROGA", _loader(TWICE), Budget(paths=1))

    assert found.coverage.total == 0
    assert not found.coverage.taken
    assert found.coverage.programs == {"TPROGA"}


CALLER = _only(
    "TPROGA",
    (_node("M/0"), _node("M/1", NodeKind.CALL), _node("M/2")),
    (_edge("M/0", "M/1"), _edge("M/1", "M/2")),
    "M/0",
)

CALLEE = _only("TPROGB", (_node("S/0"),), (), "S/0")


def _linked(reason: str = "", returns: bool = True) -> CommareaAlias:
    if reason:
        return CommareaAlias(
            caller="TPROGA", node="M/1", transfer="LINK", callee="TPROGB", reason=reason
        )
    return CommareaAlias(
        caller="TPROGA",
        node="M/1",
        transfer="LINK",
        callee="TPROGB",
        caller_extent="WS-AREA@working_storage[0:8]",
        callee_extent="DFHCOMMAREA@linkage[0:8]",
        returns=returns,
    )


def _pair(row: CommareaAlias):
    return _loader(replace(CALLER, aliases={"M/1": (row,)}), CALLEE)


def test_a_link_with_a_window_is_a_step_into_the_callee_and_back():
    """Not a wall. The callee's entry runs, then the caller resumes at the call
    node's own sequel, because ``returns`` is true for LINK."""
    assert visited_order("TPROGA", _pair(_linked()), Budget(paths=1)) == (
        "M/0",
        "M/1",
        "S/0",
        "M/2",
    )


def test_an_xctl_does_not_come_back_so_the_path_ends_in_the_callee():
    assert visited_order("TPROGA", _pair(_linked(returns=False)), Budget(paths=1)) == (
        "M/0",
        "M/1",
        "S/0",
    )


def test_a_site_with_no_window_is_a_dead_end_and_the_callers_path_goes_on():
    """The caller's own path is not over. ``transfer`` has already credited the
    commarea to ``%CALL:<program>`` exactly as the fixpoint does, so ending the
    path here would lose the caller's remaining statements for nothing."""
    found = traced("TPROGA", _pair(_linked(reason="dynamic-target")), Budget(paths=1))

    assert found.dead_ends == {
        DeadEnd(
            program="TPROGA",
            node="M/1",
            transfer="LINK",
            callee="TPROGB",
            reason="dynamic-target",
        )
    }
    assert visited_order(
        "TPROGA", _pair(_linked(reason="dynamic-target")), Budget(paths=1)
    ) == ("M/0", "M/1", "M/2")


def test_a_program_already_on_the_stack_is_not_re_entered():
    """A LINK cycle is the re-entry rule's third case, with no extra machinery: the
    callee's entry node is one an open frame has already run."""
    cyclic = _loader(
        replace(CALLER, aliases={"M/1": (_linked(),)}),
        replace(
            _only(
                "TPROGB",
                (_node("S/0", NodeKind.CALL),),
                (),
                "S/0",
            ),
            aliases={
                "S/0": (
                    CommareaAlias(
                        caller="TPROGB",
                        node="S/0",
                        transfer="LINK",
                        callee="TPROGA",
                        caller_extent="DFHCOMMAREA@linkage[0:8]",
                        callee_extent="WS-AREA@working_storage[0:8]",
                        returns=True,
                    ),
                )
            },
        ),
    )
    found = traced("TPROGA", cyclic, Budget(paths=1))

    assert {one.reason for one in found.dead_ends} == {RE_ENTRY}
    assert visited_order("TPROGA", cyclic, Budget(paths=1)) == (
        "M/0",
        "M/1",
        "S/0",
        "M/2",
    )


FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

TRACE_CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPROGA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-OUT-KEY           PIC X(4).
           05  WS-IN-RESULT         PIC X(4).
       01  WS-SEED                  PIC X(4).
       01  WS-SINK                  PIC X(4).
       01  WS-FLAG                  PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'KKKK' TO WS-SEED.
           IF WS-FLAG = 'Y'
               MOVE WS-SEED TO WS-OUT-KEY
           ELSE
               MOVE 'ZZZZ' TO WS-OUT-KEY
           END-IF.
           PERFORM LINK-PARA.
           MOVE WS-IN-RESULT TO WS-SINK.
           STOP RUN.
       LINK-PARA.
           EXEC CICS LINK PROGRAM('TPROGB')
                          COMMAREA(WS-AREA)
                          LENGTH(8)
           END-EXEC.
"""

TRACE_CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPROGB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  SUB-REC.
           05  SUB-KEY              PIC X(4).
           05  SUB-RESULT           PIC X(4).
       LINKAGE SECTION.
       01  DFHCOMMAREA              PIC X(8).
       PROCEDURE DIVISION.
       SUB-PARA.
           MOVE DFHCOMMAREA TO SUB-REC.
           MOVE SUB-KEY TO SUB-RESULT.
           MOVE SUB-RESULT TO DFHCOMMAREA(5:4).
           EXEC CICS RETURN END-EXEC.
"""

PERFORM_CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPROGC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  SUB-REC.
           05  SUB-KEY              PIC X(4).
           05  SUB-RESULT           PIC X(4).
       LINKAGE SECTION.
       01  DFHCOMMAREA              PIC X(8).
       PROCEDURE DIVISION.
       SUB-PARA.
           MOVE DFHCOMMAREA TO SUB-REC.
           PERFORM WORK-PARA.
           GOBACK.
       WORK-PARA.
           MOVE SUB-KEY TO SUB-RESULT.
           MOVE SUB-RESULT TO DFHCOMMAREA(5:4).
           GOBACK.
"""

PERFORM_CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPROGD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-OUT-KEY           PIC X(4).
           05  WS-IN-RESULT         PIC X(4).
       01  WS-SINK                  PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'KKKK' TO WS-OUT-KEY.
           PERFORM LINK-PARA.
           MOVE WS-IN-RESULT TO WS-SINK.
           STOP RUN.
       LINK-PARA.
           EXEC CICS LINK PROGRAM('TPROGC')
                          COMMAREA(WS-AREA)
                          LENGTH(8)
           END-EXEC.
"""

KILL_CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPROGE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-FIRST             PIC X(4).
       01  WS-SINK                  PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'AAAA' TO WS-FIRST.
           PERFORM LINK-PARA.
           MOVE WS-FIRST TO WS-SINK.
           STOP RUN.
       LINK-PARA.
           EXEC CICS LINK PROGRAM('TPROGF')
                          COMMAREA(WS-AREA)
                          LENGTH(4)
           END-EXEC.
"""

KILL_CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TPROGF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  SUB-REC                  PIC X(4).
       LINKAGE SECTION.
       01  DFHCOMMAREA              PIC X(4).
       PROCEDURE DIVISION.
       SUB-PARA.
           MOVE 'BBBB' TO SUB-REC.
           MOVE SUB-REC TO DFHCOMMAREA.
           GOBACK.
"""


def _bridge_jar() -> Path:
    """The parse is the only thing here that needs a JVM, so it is the only thing
    that can make this half unrunnable. A missing JAR is an unbuilt workspace, not
    a failing analysis: ``make jar`` at the root builds it."""
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


@pytest.fixture(scope="module")
def parsed(tmp_path_factory) -> Path:
    """Both members parsed for real. One JVM start, because that is the cost being
    amortised -- every test below asks a question of the same cache."""
    from cobble.parsing.parse_corpus import Job, parse_one

    root = tmp_path_factory.mktemp("trace")
    cache = root / "asg"
    cache.mkdir()
    for program, source in (("TPROGA", TRACE_CALLER), ("TPROGB", TRACE_CALLEE)):
        path = root / f"{program}.cbl"
        path.write_text(source, encoding="utf-8")
        result = parse_one(
            Job(path, cache / f"{program}.json"), str(_bridge_jar()), (), ("cpy",)
        )
        assert result.ok, result.error
    return cache


@pytest.fixture(scope="module")
def crossed(parsed: Path) -> Trace:
    return sampled("TPROGA", parsed, Budget(paths=8))


@pytest.fixture(scope="module")
def parsed_perform(tmp_path_factory) -> Path:
    """A callee whose GOBACK sits inside a PERFORMed paragraph. Regression for
    C1: _ended must unwind to the crossing frame, not just look at stack[-1]."""
    from cobble.parsing.parse_corpus import Job, parse_one

    root = tmp_path_factory.mktemp("trace_perform")
    cache = root / "asg"
    cache.mkdir()
    for program, source in (("TPROGD", PERFORM_CALLER), ("TPROGC", PERFORM_CALLEE)):
        path = root / f"{program}.cbl"
        path.write_text(source, encoding="utf-8")
        result = parse_one(
            Job(path, cache / f"{program}.json"), str(_bridge_jar()), (), ("cpy",)
        )
        assert result.ok, result.error
    return cache


@pytest.fixture(scope="module")
def crossed_perform(parsed_perform: Path) -> Trace:
    return sampled("TPROGD", parsed_perform, Budget(paths=8))


@pytest.fixture(scope="module")
def parsed_kill(tmp_path_factory) -> Path:
    """A callee that kills bytes the caller held. Guards the state.write constraint.

    The commarea is exactly as wide as the callee's write, and the write is a whole
    move rather than a reference modification: ``must_cover`` under-approximates, so
    a narrower or CLAMPED write kills nothing and ``join`` would look identical.
    """
    from cobble.parsing.parse_corpus import Job, parse_one

    root = tmp_path_factory.mktemp("trace_kill")
    cache = root / "asg"
    cache.mkdir()
    for program, source in (("TPROGE", KILL_CALLER), ("TPROGF", KILL_CALLEE)):
        path = root / f"{program}.cbl"
        path.write_text(source, encoding="utf-8")
        result = parse_one(
            Job(path, cache / f"{program}.json"), str(_bridge_jar()), (), ("cpy",)
        )
        assert result.ok, result.error
    return cache


@pytest.fixture(scope="module")
def crossed_kill(parsed_kill: Path) -> Trace:
    return sampled("TPROGE", parsed_kill, Budget(paths=8))


def test_a_callee_write_kills_the_callers_old_definition(crossed_kill):
    """I1: _restored uses state.write per extent, not state.join. No caller-side
    source at those bytes survives the write-back -- the one the call site itself
    left there included."""
    (dep,) = [
        one
        for one in crossed_kill.deps
        if one.program == "TPROGE" and one.target.field_name == "WS-SINK"
    ]

    assert not [one for one in dep.definers if one.startswith("TPROGE/")]
    assert [one for one in dep.definers if one.startswith("TPROGF/")]


def test_a_callee_ending_in_a_performed_paragraph_seeds_the_caller_back(
    crossed_perform,
):
    """C1 regression: when a LINK callee's path ends inside a PERFORMed paragraph,
    _ended must unwind to the crossing frame rather than stopping at stack[-1]. The
    caller's sink must witness the callee's write through DFHCOMMAREA."""
    (dep,) = [
        one
        for one in crossed_perform.deps
        if one.program == "TPROGD" and one.target.field_name == "WS-SINK"
    ]

    assert str(dep.source) == "WS-IN-RESULT@working_storage[4:8]"
    assert [one for one in dep.definers if one.startswith("TPROGC/")]


def test_the_walk_enters_the_callee_and_witnesses_writes_in_both_members(crossed):
    assert {one.program for one in crossed.deps} == {"TPROGA", "TPROGB"}


def test_the_callees_writes_are_credited_to_the_call_site_they_were_reached_through(
    crossed,
):
    """``via`` is how a reader reconstructs the route without the walk printing
    every node it passed through."""
    inside = {one.via for one in crossed.deps if one.program == "TPROGB"}

    assert len(inside) == 1
    assert next(iter(inside)).startswith("TPROGA/LINK-PARA/")


def test_the_callee_reads_bytes_the_caller_defined(crossed):
    """The inbound direction, and the whole point. SUB-REC is written from
    DFHCOMMAREA, whose bytes the caller's own MOVE put there -- so the definer is
    a node in a different member, which no intra-program walk can name."""
    (dep,) = [
        one
        for one in crossed.deps
        if one.program == "TPROGB" and one.target.field_name == "SUB-REC"
    ]

    assert str(dep.source).startswith("DFHCOMMAREA@linkage[0:8]")
    assert [one for one in dep.definers if one.startswith("TPROGA/")]


def test_the_callers_sink_reads_bytes_the_callee_defined(crossed):
    """The return direction, which needs no mechanism at all: the callee's write
    through DFHCOMMAREA(5:4) landed on the caller's own WS-IN-RESULT, because in a
    byte-addressable model the two were never separate storage."""
    (dep,) = [
        one
        for one in crossed.deps
        if one.program == "TPROGA" and one.target.field_name == "WS-SINK"
    ]

    assert str(dep.source) == "WS-IN-RESULT@working_storage[4:8]"
    assert [one for one in dep.definers if one.startswith("TPROGB/")]


def test_both_arms_of_the_branch_are_witnessed_across_the_sampled_paths(crossed):
    """One path sees one arm. Sampling is what gets the other, and it is why a
    single path's answer would be a narrower claim than this tool makes."""
    origins = {
        one.origin
        for one in crossed.deps
        if one.program == "TPROGA" and one.target.field_name == "WS-OUT-KEY"
    }
    sources = {
        str(one.source)
        for one in crossed.deps
        if one.program == "TPROGA" and one.target.field_name == "WS-OUT-KEY"
    }

    assert "LITERAL" in origins
    assert any(text.startswith("WS-SEED@") for text in sources)


def test_the_coverage_denominator_comes_from_the_graphs_and_not_from_the_answer(
    crossed, parsed: Path
):
    """The 3ao post-mortem's lesson: a denominator taken from the walk's own output
    makes every suite pass at 100%. Recomputed here from the parsed graphs instead,
    never written down as a constant -- ``desugar`` gives every ``EXEC CICS`` command
    with no NOHANDLE and no RESP a ``#raise`` test, so the real count is well above
    the one ``IF`` a reader of the fixture source can see.
    """
    graphs = tuple(_loaded(parsed, one).cfg for one in ("TPROGA", "TPROGB"))
    edges = tuple(one for cfg in graphs for one in _branch_edges(cfg))

    assert crossed.coverage.programs == {"TPROGA", "TPROGB"}
    assert crossed.coverage.total == len(edges)
    assert crossed.coverage.taken
    assert crossed.coverage.taken <= frozenset(edges)


def test_a_member_absent_from_the_cache_is_refused_before_any_path_runs(parsed: Path):
    """A wrong ``--asg-dir`` is a mistake about the invocation, not a finding about
    the corpus, so it never reaches the sampler."""
    assert loadable(parsed, "TPROGA") == ""
    assert "no ASG cache" in loadable(parsed, "TPROGZ")


def test_the_report_groups_by_program_and_names_the_site_each_was_entered_through(
    parsed: Path, tmp_path: Path
):
    from cobble.dataflow.fields.trace_report import cli

    out = tmp_path / "trace.txt"
    assert (
        cli(
            [
                "TPROGA",
                "--asg-dir",
                str(parsed),
                "--out",
                str(out),
                "--paths",
                "8",
            ]
        )
        == 0
    )
    written = out.read_text(encoding="utf-8")

    assert "TPROGA\n" in written
    assert "TPROGB   via TPROGA/LINK-PARA/" in written
    assert "branch coverage:" in written
    assert "programs entered" in written


def test_the_report_states_its_limits_where_a_reader_will_see_them(
    parsed: Path, tmp_path: Path
):
    """In the output, not only in the design doc. The query-time stop layer was
    deleted for being unreadable, and a number a reader can act on is what replaced
    it."""
    from cobble.dataflow.fields.trace_report import cli

    out = tmp_path / "trace.txt"
    assert cli(["TPROGA", "--asg-dir", str(parsed), "--out", str(out)]) == 0
    written = out.read_text(encoding="utf-8")

    assert "limits:" in written
    assert 'absence means "not sampled"' in written


def test_a_definer_that_crossed_a_call_is_spelled_with_the_member_it_is_in(
    parsed: Path, tmp_path: Path
):
    """The payload no existing artefact can carry: the caller's sink names a node
    in the callee as the last writer of its bytes."""
    from cobble.dataflow.fields.trace_report import cli

    out = tmp_path / "trace.txt"
    assert cli(["TPROGA", "--asg-dir", str(parsed), "--out", str(out)]) == 0
    written = out.read_text(encoding="utf-8")

    assert "defined at TPROGB/SUB-PARA/" in written


def test_a_missing_cache_directory_is_refused_with_a_status_and_not_a_traceback(
    tmp_path: Path,
):
    from cobble.dataflow.fields.trace_report import cli

    assert (
        cli(
            [
                "TPROGA",
                "--asg-dir",
                str(tmp_path / "absent"),
                "--out",
                str(tmp_path / "trace.txt"),
            ]
        )
        == 2
    )


def test_positive_validator_accepts_positive_integers():
    from cobble.dataflow.fields.trace_report import _positive

    assert _positive("1") == 1
    assert _positive("100") == 100


def test_positive_validator_rejects_zero_and_negative():
    import argparse

    from cobble.dataflow.fields.trace_report import _positive

    with pytest.raises(argparse.ArgumentTypeError):
        _positive("0")
    with pytest.raises(argparse.ArgumentTypeError):
        _positive("-1")


def test_fraction_validator_accepts_valid_fractions():
    from cobble.dataflow.fields.trace_report import _fraction

    assert _fraction("0.5") == 0.5
    assert _fraction("1.0") == 1.0
    assert _fraction("0.01") == 0.01


def test_fraction_validator_rejects_out_of_range_fractions():
    import argparse

    from cobble.dataflow.fields.trace_report import _fraction

    with pytest.raises(argparse.ArgumentTypeError):
        _fraction("0.0")
    with pytest.raises(argparse.ArgumentTypeError):
        _fraction("1.1")
    with pytest.raises(argparse.ArgumentTypeError):
        _fraction("-0.1")


def test_each_sampled_path_logs_a_progress_line(caplog):
    """A run of any size is otherwise silent until the report is written, so the
    coverage figure a reader needs to judge --paths arrives only after the run it
    would have changed."""
    caplog.set_level(logging.INFO, logger="cobble.dataflow.fields.trace")

    traced("TPROGA", _loader(LOOP), Budget(paths=50, coverage=1.0))

    paths = [one for one in caplog.messages if one.startswith("trace: [")]
    assert len(paths) == 2
    assert paths[0].startswith("trace: [1/50]")
    assert paths[1].startswith("trace: [2/50]")
    assert "2/2 branches (100%)" in paths[1]


def test_the_closing_line_separates_a_met_target_from_a_spent_budget(caplog):
    """The per-path lines cannot say why the run stopped, and the two reasons call
    for opposite responses: raise --paths, or accept the coverage as the ceiling."""
    caplog.set_level(logging.INFO, logger="cobble.dataflow.fields.trace")

    traced("TPROGA", _loader(LOOP), Budget(paths=50, coverage=1.0))
    (met,) = [one for one in caplog.messages if one.startswith("trace: 2 paths")]
    assert "coverage target met" in met

    caplog.clear()
    traced("TPROGA", _loader(LOOP), Budget(paths=1, coverage=1.0))
    (spent,) = [one for one in caplog.messages if one.startswith("trace: 1 path")]
    assert "path budget ran out" in spent
