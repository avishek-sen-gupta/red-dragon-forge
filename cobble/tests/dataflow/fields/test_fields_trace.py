"""The path walk: its stack rules on graphs built here, its crossing on a real parse.

Two halves, because they fail for different reasons. The stack rules -- unroll a
loop once, let a paragraph PERFORMed twice run twice, take only your own RETURN
edge -- are decided by the walk alone, so they are asserted against CFGs written
out in this file where every node id is chosen here. The crossing is decided by
the bridge's layout arithmetic, which no hand-built extent can stand in for: a
rebase that is off by a byte agrees with a fixture and disagrees with COBOL.
"""

from __future__ import annotations

from cobble.dataflow.fields.side_tables import CommareaAlias
from cobble.dataflow.fields.state import Source, write
from cobble.dataflow.fields.trace import (
    NO_WINDOW,
    Budget,
    Loaded,
    _extent_at,
    _rebased,
    _seeded,
    _window,
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
    found = _extent_at("WS-AREA@working_storage[8:20]", "TPROGA")

    assert found.region is RegionId.WORKING_STORAGE
    assert (found.start, found.length) == (8, 12)
    assert found.field_name == "WS-AREA"
    assert found.precision is Precision.EXACT


def test_a_text_that_is_not_an_extent_parses_to_a_length_of_nothing():
    """A dead-end alias row carries a reason where the extents would be. Zero
    length is what makes that safe to carry in an extent-shaped slot: may_alias
    and must_cover both reject a non-positive length."""
    assert not _extent_at("", "TPROGA").length
    assert not _extent_at("callee-not-in-cache", "TPROGA").length


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
    assert found.coverage.programs == {"TPROGA"}
