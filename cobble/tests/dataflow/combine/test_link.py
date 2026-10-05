"""Linking: values cross programs over a call graph that grows from those values."""

from collections.abc import Mapping

from cobble.dataflow.combine.callee_areas import CalleeAreas
from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.link import link
from cobble.dataflow.combine.linked import Linked
from cobble.dataflow.combine.outside_jumps import OutsideJumps
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.run_report import RunReport
from cobble.dataflow.combine.target_site import TargetSite
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_area import JumpArea
from cobble.dataflow.jumps.jump_kind import JumpKind


class FakeAreas(CalleeAreas):
    def __init__(self, areas: Mapping[tuple[str, int], str]) -> None:
        self._areas = areas

    def area(self, callee: str, kind: JumpKind, param: int) -> ByteRange:
        text = self._areas.get((callee, param), "")
        return byte_range(text, callee) if text else NO_RANGE


def _facts(program: str, facts: tuple[Fact, ...]) -> tuple[tuple[ByteRange, Fact], ...]:
    return tuple((byte_range(fact.extent, program), fact) for fact in facts)


def caller(name: str, stamp: str, to: str, width: int = 20) -> ProgramTables:
    fields = (
        Fact("WS-FROM@working_storage[0:8]", values=(stamp.ljust(8),), writers=("S",)),
        Fact(
            "WS-REST@working_storage[8:20]", reasons=(UnresolvedReason.UNINITIALISED,)
        ),
    )
    jump = Jump(
        name,
        "X",
        9,
        JumpKind.XCTL,
        False,
        target=Fact(values=(to,)),
        areas=(JumpArea(0, f"WS-AREA@working_storage[0:{width}]", fields),),
    )
    return ProgramTables(
        name,
        facts={"X": _facts(name, fields)},
        flows={},
        jumps={"X": jump},
        received=((0, byte_range("DFHCOMMAREA@linkage[0:20]", name)),),
        sites={},
    )


def returner(
    name: str, fallback: str, more: Mapping[str, tuple[Jump, tuple[Fact, ...]]] = {}
) -> ProgramTables:
    ws = byte_range("WS-NEXT@working_storage[0:8]", name)
    lk = byte_range("LK-FROM@linkage[0:8]", name)
    inbound = Fact("LK-FROM@linkage[0:8]", reasons=(UnresolvedReason.INBOUND_LINKAGE,))
    target = Fact(
        "WS-NEXT@working_storage[0:8]",
        values=(fallback.ljust(8),),
        writers=("M1", "M2"),
    )
    jump = Jump(
        name,
        "X",
        9,
        JumpKind.XCTL,
        False,
        target=target,
        areas=(JumpArea(0, "DFHCOMMAREA@linkage[0:20]", (inbound,)),),
    )
    return ProgramTables(
        name,
        facts={
            "X": _facts(name, (target, inbound)),
            "M2": ((lk, inbound),),
            **{node: _facts(name, facts) for node, (_, facts) in more.items()},
        },
        flows={"M1": (Flow("M1", NO_RANGE, ws),), "M2": (Flow("M2", lk, ws),)},
        jumps={"X": jump, **{node: j for node, (j, _) in more.items()}},
        received=((0, byte_range("DFHCOMMAREA@linkage[0:20]", name)),),
        sites={"X": TargetSite("CICS_XCTL", "WS-NEXT")},
    )


def areas(*names: str) -> FakeAreas:
    return FakeAreas({(n, 0): "DFHCOMMAREA@linkage[0:20]" for n in names})


def _row(
    linked: Linked, program: str
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    (found,) = [t for t in linked.targets if t.target.caller == program]
    return (
        found.target.candidates,
        tuple(r.value for r in found.target.reasons),
        found.outside,
    )


def test_return_to_caller_resolves_to_every_program_that_jumps_in() -> None:
    linked = link(
        {"A": caller("A", "A", "B"), "B": returner("B", "M")},
        areas("A", "B"),
        {},
        OutsideJumps(unresolved=2, without_results=("Z",)),
    )
    assert _row(linked, "B") == (("A", "M"), (), ())
    assert {(e.caller, e.callee, e.discovered) for e in linked.edges} == {
        ("A", "B", False),
        ("B", "A", True),
    }
    assert linked.report == RunReport(
        rounds=3, discovered=1, unresolved_outside_jumps=2, without_results=("Z",)
    )


def test_a_target_found_only_across_programs_grows_the_call_graph() -> None:
    tables = {
        "C": caller("C", "R", "P"),
        "P": returner("P", "M"),
        "R": returner("R", "Q"),
    }
    linked = link(tables, areas("C", "P", "R"), {}, OutsideJumps())
    assert _row(linked, "P") == (("M", "R"), (), ())
    assert {(e.caller, e.callee, e.discovered) for e in linked.edges} == {
        ("C", "P", False),
        ("P", "R", True),
        ("R", "R", True),
    }
    assert _row(linked, "R") == (("Q", "R"), (), ())


def test_a_cycle_that_adds_nothing_terminates_with_no_invented_candidates() -> None:
    linked = link(
        {"A": returner("A", "B"), "B": returner("B", "A")},
        areas("A", "B"),
        {},
        OutsideJumps(),
    )
    assert (_row(linked, "A"), _row(linked, "B")) == (
        (("B",), (), ()),
        (("A",), (), ()),
    )
    relayed = link(
        {"A": relay("A", "B"), "B": relay("B", "A")},
        areas("A", "B"),
        {},
        OutsideJumps(),
    )
    assert (_row(relayed, "A"), _row(relayed, "B")) == (
        ((), ("inbound-linkage",), ()),
        ((), ("inbound-linkage",), ()),
    )


def relay(name: str, to: str) -> ProgramTables:
    lk = byte_range("LK-FROM@linkage[0:8]", name)
    inbound = Fact("LK-FROM@linkage[0:8]", reasons=(UnresolvedReason.INBOUND_LINKAGE,))
    onward = Jump(
        name,
        "J",
        7,
        JumpKind.XCTL,
        False,
        target=Fact(values=(to,)),
        areas=(JumpArea(0, "DFHCOMMAREA@linkage[0:20]", (inbound,)),),
    )
    site = Jump(name, "X", 9, JumpKind.XCTL, False, target=inbound)
    return ProgramTables(
        name,
        facts={"J": ((lk, inbound),), "X": ((lk, inbound),)},
        flows={},
        jumps={"J": onward, "X": site},
        received=((0, byte_range("DFHCOMMAREA@linkage[0:20]", name)),),
        sites={"X": TargetSite("CICS_XCTL", "LK-FROM")},
    )


def test_a_window_narrower_than_the_bytes_contributes_nothing() -> None:
    linked = link(
        {"A": caller("A", "A", "B"), "B": returner("B", "M")},
        FakeAreas({("B", 0): "DFHCOMMAREA@linkage[0:4]"}),
        {},
        OutsideJumps(),
    )
    assert _row(linked, "B") == (("M",), ("inbound-linkage",), ())
    mixed = link(
        {
            "A": caller("A", "A", "B"),
            "C": caller("C", "C", "B", width=4),
            "B": returner("B", "M"),
        },
        areas("A", "B", "C"),
        {},
        OutsideJumps(),
    )
    assert _row(mixed, "B") == (("A", "M"), ("inbound-linkage",), ())


def test_an_outside_caller_with_a_known_target_is_named() -> None:
    linked = link(
        {"B": returner("B", "M")},
        areas("B"),
        {},
        OutsideJumps(known_into={"B": ("OUT1",)}),
    )
    assert _row(linked, "B") == (
        ("M",),
        ("inbound-linkage", "outside-analysed-set"),
        ("OUT1",),
    )


def test_return_transid_re_enters_the_programs_own_entry() -> None:
    handed = Fact("LK-FROM@linkage[0:8]", values=("A       ",))
    again = Jump(
        "B",
        "T",
        12,
        JumpKind.RETURN_TRANSID,
        False,
        transid=Fact(values=("TRNB",)),
        areas=(JumpArea(0, "DFHCOMMAREA@linkage[0:20]", (handed,)),),
    )
    linked = link(
        {"B": returner("B", "M", {"T": (again, (handed,))})},
        areas("B"),
        {"TRNB": "B"},
        OutsideJumps(),
    )
    assert _row(linked, "B") == (("A", "M"), (), ())
    assert {(e.caller, e.node, e.kind, e.callee) for e in linked.edges} == {
        ("B", "T", JumpKind.RETURN_TRANSID, "B")
    }


def _started(width: int) -> Mapping[str, ProgramTables]:
    extent = f"WS-MSG@working_storage[0:{width}]"
    message = Fact(extent, values=("PROGZ   "[:width],))
    start = Jump(
        "S",
        "ST",
        4,
        JumpKind.START,
        False,
        transid=Fact(values=("TRNR",)),
        areas=(JumpArea(0, extent, (message,)),),
    )
    into = byte_range("WS-IN@working_storage[0:8]", "R")
    target = Fact("WS-IN@working_storage[0:8]", writers=("RT",))
    retrieve = Jump(
        "R",
        "RT",
        3,
        JumpKind.RETRIEVE,
        False,
        areas=(JumpArea(0, "WS-IN@working_storage[0:8]"),),
    )
    xctl = Jump("R", "X", 9, JumpKind.XCTL, False, target=target)
    return {
        "S": ProgramTables(
            "S",
            facts={"ST": _facts("S", (message,))},
            flows={},
            jumps={"ST": start},
            received=(),
            sites={},
        ),
        "R": ProgramTables(
            "R",
            facts={"X": ((into, target),)},
            flows={"RT": (Flow("RT", NO_RANGE, into),)},
            jumps={"RT": retrieve, "X": xctl},
            received=(),
            sites={"X": TargetSite("CICS_XCTL", "WS-IN")},
        ),
    }


def test_start_from_reaches_the_started_programs_retrieve() -> None:
    linked = link(_started(8), areas(), {"TRNR": "R"}, OutsideJumps())
    narrow = link(_started(4), areas(), {"TRNR": "R"}, OutsideJumps())
    assert _row(linked, "R") == (("PROGZ",), (), ())
    assert {(e.caller, e.kind, e.callee, e.callee_node) for e in linked.edges} == {
        ("S", JumpKind.START, "R", "RT")
    }
    assert _row(narrow, "R") == ((), ("not-a-literal",), ())


def _linker(name: str) -> ProgramTables:
    ws = byte_range("WS-NEXT@working_storage[0:8]", name)
    target = Fact("WS-NEXT@working_storage[0:8]", writers=("L",))
    call = Jump(
        name,
        "L",
        5,
        JumpKind.LINK,
        True,
        target=Fact(values=("W",)),
        areas=(JumpArea(0, "WS-AREA@working_storage[0:20]"),),
    )
    xctl = Jump(name, "X", 9, JumpKind.XCTL, False, target=target)
    return ProgramTables(
        name,
        facts={"X": ((ws, target),)},
        flows={"L": (Flow("L", NO_RANGE, ws),)},
        jumps={"L": call, "X": xctl},
        received=(),
        sites={"X": TargetSite("CICS_XCTL", "WS-NEXT")},
    )


def _writer(value: str, exits: bool) -> ProgramTables:
    left = Fact("LK-FROM@linkage[0:8]", values=(value,))
    exit_ = Jump(
        "W",
        "E",
        20,
        JumpKind.EXIT,
        False,
        areas=(JumpArea(0, "DFHCOMMAREA@linkage[0:20]", (left,)),),
    )
    return ProgramTables(
        "W",
        facts={"E": _facts("W", (left,))},
        flows={},
        jumps={"E": exit_} if exits else {},
        received=((0, byte_range("DFHCOMMAREA@linkage[0:20]", "W")),),
        sites={},
    )


def test_a_link_write_back_reaches_the_callers_later_jump() -> None:
    narrow = FakeAreas(
        {("A", 0): "DFHCOMMAREA@linkage[0:20]", ("W", 0): "DFHCOMMAREA@linkage[0:4]"}
    )
    rows = tuple(
        _row(link(tables, given, {}, OutsideJumps()), "A")
        for tables, given in (
            ({"A": _linker("A"), "W": _writer("Q       ", True)}, areas("A", "W")),
            ({"A": _linker("A")}, areas("A", "W")),
            ({"A": _linker("A"), "W": _writer("QWERTYUI", True)}, narrow),
            ({"A": _linker("A"), "W": _writer("Q       ", False)}, areas("A", "W")),
        )
    )
    assert rows == (
        (("Q",), (), ()),
        ((), ("from-callee",), ()),
        ((), ("from-callee",), ()),
        ((), ("from-callee",), ()),
    )


def test_a_site_whose_target_has_no_extent_keeps_its_reason() -> None:
    blind = Jump(
        "N",
        "X",
        9,
        JumpKind.XCTL,
        False,
        target=Fact(reasons=(UnresolvedReason.NO_EXTENT,)),
    )
    tables = ProgramTables(
        "N",
        facts={},
        flows={},
        jumps={"X": blind},
        received=(),
        sites={"X": TargetSite("CICS_XCTL", "WS-GONE")},
    )
    linked = link({"N": tables}, areas(), {}, OutsideJumps())
    assert (_row(linked, "N"), linked.edges) == (((), ("no-extent",), ()), ())
