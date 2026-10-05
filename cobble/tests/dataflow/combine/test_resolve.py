"""resolve: what some bytes hold at a node, back to the stops linking follows."""

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.resolution import Resolution
from cobble.dataflow.combine.resolve import resolve
from cobble.dataflow.combine.stop import Stop
from cobble.dataflow.combine.stop_kind import StopKind
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.jump_kind import JumpKind

P = "PROGB"


def r(text: str) -> ByteRange:
    return byte_range(text, P)


def tables(
    facts: dict[str, tuple[tuple[ByteRange, Fact], ...]],
    flows: dict[str, tuple[Flow, ...]],
    jumps: dict[str, Jump] = {},
) -> ProgramTables:
    return ProgramTables(
        program=P,
        facts=facts,
        flows=flows,
        jumps=jumps,
        received=((0, r("DFHCOMMAREA@linkage[0:20]")),),
        sites={},
    )


LK = r("LK-FROM@linkage[0:8]")
WS = r("WS-NEXT@working_storage[0:8]")
TMP = r("WS-TMP@working_storage[8:20]")


def test_received_bytes_are_found_through_several_copies_of_different_widths() -> None:
    t = tables(
        facts={
            "J": ((WS, Fact("WS-NEXT@working_storage[0:8]", writers=("M2",))),),
            "M2": ((TMP, Fact("WS-TMP@working_storage[8:20]", writers=("M1",))),),
            "M1": (
                (
                    LK,
                    Fact(
                        "LK-FROM@linkage[0:8]",
                        reasons=(UnresolvedReason.INBOUND_LINKAGE,),
                    ),
                ),
            ),
        },
        flows={
            "M2": (Flow("M2", r("WS-TMP@working_storage[8:16]"), WS),),
            "M1": (Flow("M1", LK, r("WS-TMP@working_storage[8:16]")),),
        },
    )
    assert resolve(t, "J", WS) == Resolution(
        stops=frozenset(
            {Stop(StopKind.RECEIVED, at=r("LK-FROM@linkage[0:8]"), param=0)}
        )
    )


def test_a_reference_modified_copy_rebases_onto_the_right_source_bytes() -> None:
    t = tables(
        facts={
            "J": ((WS, Fact("WS-NEXT@working_storage[0:8]", writers=("M1",))),),
            "M1": ((r("LK-AREA@linkage[0:20]"), Fact("LK-AREA@linkage[0:20]")),),
        },
        flows={"M1": (Flow("M1", r("LK-AREA@linkage[12:20]"), WS),)},
    )
    (stop,) = resolve(t, "J", r("WS-NEXT@working_storage[2:6]")).stops
    assert (stop.kind, stop.at.start, stop.at.end) == (StopKind.RECEIVED, 14, 18)


def test_bytes_left_by_a_link_and_a_call_stop_as_returned_in_the_right_area() -> None:
    call = Jump(
        P,
        "C",
        5,
        JumpKind.CALL,
        True,
        areas=(
            JumpArea(0, "WS-A@working_storage[0:4]"),
            JumpArea(1, "WS-B@working_storage[4:12]"),
        ),
    )
    b = r("WS-B@working_storage[4:12]")
    t = tables(
        facts={"J": ((b, Fact("WS-B@working_storage[4:12]", writers=("C",))),)},
        flows={"C": (Flow("C", NO_RANGE, b),)},
        jumps={"C": call},
    )
    assert resolve(t, "J", b).stops == frozenset(
        {Stop(StopKind.RETURNED, at=b, node="C", param=1)}
    )


def test_a_retrieve_stop_is_decided_by_its_node_not_its_reason() -> None:
    y = r("WS-Y@working_storage[0:6]")
    retrieve = Jump(
        P,
        "R",
        3,
        JumpKind.RETRIEVE,
        False,
        areas=(JumpArea(0, "WS-Y@working_storage[0:6]"),),
    )
    t = tables(
        facts={
            "J": (
                (
                    y,
                    Fact(
                        "WS-Y@working_storage[0:6]",
                        writers=("R",),
                        reasons=(UnresolvedReason.NOT_A_LITERAL,),
                    ),
                ),
            )
        },
        flows={"R": (Flow("R", NO_RANGE, y),)},
        jumps={"R": retrieve},
    )
    assert resolve(t, "J", y).stops == frozenset(
        {Stop(StopKind.RETRIEVED, at=y, node="R")}
    )
    unsettled = tables(
        facts={
            "J": (
                (
                    y,
                    Fact(
                        "WS-Y@working_storage[0:6]",
                        writers=("R",),
                        reasons=(UnresolvedReason.INCOMPLETE_WALK,),
                    ),
                ),
            )
        },
        flows={"R": (Flow("R", NO_RANGE, y),)},
        jumps={"R": retrieve},
    )
    assert resolve(unsettled, "J", y).stops == frozenset(
        {
            Stop(StopKind.RETRIEVED, at=y, node="R"),
            Stop(StopKind.UNKNOWN, reasons=(UnresolvedReason.INCOMPLETE_WALK,)),
        }
    )


def test_a_literal_write_inside_the_walk_contributes_its_value_only() -> None:
    t = tables(
        facts={
            "J": (
                (
                    WS,
                    Fact(
                        "WS-NEXT@working_storage[0:8]",
                        values=("PROGM   ",),
                        writers=("M1",),
                    ),
                ),
            )
        },
        flows={"M1": (Flow("M1", NO_RANGE, WS),)},
    )
    assert resolve(t, "J", WS) == Resolution(values=frozenset({"PROGM   "}))
    unsettled = tables(
        facts={
            "J": (
                (
                    WS,
                    Fact(
                        "WS-NEXT@working_storage[0:8]",
                        values=("PROGM   ",),
                        writers=("M1",),
                        reasons=(UnresolvedReason.INCOMPLETE_WALK,),
                    ),
                ),
            )
        },
        flows={"M1": (Flow("M1", NO_RANGE, WS),)},
    )
    assert resolve(unsettled, "J", WS) == Resolution(
        values=frozenset({"PROGM   "}),
        stops=frozenset(
            {Stop(StopKind.UNKNOWN, reasons=(UnresolvedReason.INCOMPLETE_WALK,))}
        ),
    )


def test_a_computed_value_stops_as_unknown_with_its_reason() -> None:
    n = r("WS-N@working_storage[0:4]")
    t = tables(
        facts={
            "J": (
                (
                    n,
                    Fact(
                        "WS-N@working_storage[0:4]",
                        reasons=(UnresolvedReason.UNINITIALISED,),
                    ),
                ),
            )
        },
        flows={},
    )
    assert resolve(t, "J", n) == Resolution(
        stops=frozenset(
            {Stop(StopKind.UNKNOWN, reasons=(UnresolvedReason.UNINITIALISED,))}
        )
    )
    unreached = tables(
        facts={
            "J": (
                (
                    n,
                    Fact(
                        "WS-N@working_storage[0:4]",
                        reasons=(
                            UnresolvedReason.UNINITIALISED,
                            UnresolvedReason.INCOMPLETE_WALK,
                        ),
                    ),
                ),
            )
        },
        flows={},
    )
    assert resolve(unreached, "J", n) == Resolution(
        stops=frozenset(
            {
                Stop(
                    StopKind.UNKNOWN,
                    reasons=(
                        UnresolvedReason.UNINITIALISED,
                        UnresolvedReason.INCOMPLETE_WALK,
                    ),
                )
            }
        )
    )


def test_no_facts_at_a_point_is_reported_not_guessed() -> None:
    assert resolve(tables(facts={}, flows={}), "J", WS) == Resolution(
        stops=frozenset(
            {Stop(StopKind.UNKNOWN, reasons=(UnresolvedReason.NOT_RECORDED,))}
        )
    )


def test_a_copy_loop_inside_one_program_terminates() -> None:
    a, b = r("WS-A@working_storage[0:4]"), r("WS-B@working_storage[4:8]")
    t = tables(
        facts={
            "J": ((a, Fact("WS-A@working_storage[0:4]", writers=("M1",))),),
            "M1": ((b, Fact("WS-B@working_storage[4:8]", writers=("M2",))),),
            "M2": ((a, Fact("WS-A@working_storage[0:4]", writers=("M1",))),),
        },
        flows={"M1": (Flow("M1", b, a),), "M2": (Flow("M2", a, b),)},
    )
    assert resolve(t, "J", a) == Resolution()
