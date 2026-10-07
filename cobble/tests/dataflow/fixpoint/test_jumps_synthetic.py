"""jumps.jsonl, compiled by the real bridge: one row per jump, exit, RETRIEVE and entry."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint.fixpoint import analysed
from cobble.dataflow.fixpoint.options import AnalysisOptions
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_from_row
from cobol_asg.asg_types import CobolASG

BASELINE = Path(__file__).parent / "data" / "jumps_baseline"

CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-FROM          PIC X(8).
           05  WS-REST          PIC X(12).
       01  WS-NEXT              PIC X(8) VALUE 'PROGB'.
       01  WS-ONE               PIC X(4).
       01  WS-TWO               PIC X(4).
       01  WS-THREE             PIC X(4).
       01  WS-TBL.
           05  WS-ROW           PIC X(4) OCCURS 3.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGA' TO WS-FROM.
           CALL 'SUBP' USING WS-ONE WS-TWO WS-THREE.
           EXEC CICS LINK PROGRAM('PROGB') COMMAREA(WS-ROW(1)) END-EXEC.
           EXEC CICS XCTL PROGRAM(WS-NEXT) COMMAREA(WS-AREA) END-EXEC.
"""

CICSB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                 PIC X(6) VALUE 'HELLO'.
       01  WS-Y                 PIC X(6).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS RETRIEVE INTO(WS-Y) END-EXEC.
           EXEC CICS START TRANSID('TRNC') FROM(WS-X) END-EXEC.
           EXEC CICS RETURN TRANSID('TRNB')
               COMMAREA(DFHCOMMAREA) END-EXEC.
"""

SUBP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBP.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-1                 PIC X(4).
       01  LK-2                 PIC X(4).
       01  LK-3                 PIC X(4).
       PROCEDURE DIVISION USING LK-1 LK-2 LK-3.
       MAIN-PARA.
           MOVE 'ABCD' TO LK-1.
           GOBACK.
"""

SOURCES = {"PROGA": CALLER, "PROGB": CICSB, "SUBP": SUBP}
EXISTING = ("defs.jsonl", "graph.jsonl", "targets.jsonl", "aliases.jsonl")


@pytest.fixture(scope="module")
def out(fixpoint_corpus: Callable[[Mapping[str, str]], Path]) -> Path:
    return fixpoint_corpus(SOURCES)


def _jumps(out: Path, program: str) -> tuple[Jump, ...]:
    lines = (
        (out / "members" / program / "jumps.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    return tuple(jump_from_row(line) for line in lines)


def _by_kind(jumps: tuple[Jump, ...], kind: JumpKind) -> tuple[Jump, ...]:
    return tuple(jump for jump in jumps if jump.kind is kind)


def test_an_xctl_hands_over_its_commarea_field_by_field(out: Path) -> None:
    (xctl,) = _by_kind(_jumps(out, "PROGA"), JumpKind.XCTL)
    (area,) = xctl.areas
    assert (xctl.target.values, area.param, area.extent) == (
        ("PROGB   ",),
        0,
        "WS-AREA@working_storage[0:20]",
    )
    assert [(f.extent, f.values, f.writers, f.reasons) for f in area.fields] == [
        ("WS-FROM@working_storage[0:8]", ("PROGA   ",), ("MAIN-PARA/0",), ()),
        (
            "WS-REST@working_storage[8:20]",
            (),
            (),
            (UnresolvedReason.UNINITIALISED,),
        ),
    ]


def test_a_call_hands_over_one_area_per_using_argument(out: Path) -> None:
    (call,) = _by_kind(_jumps(out, "PROGA"), JumpKind.CALL)
    assert (call.returns, call.target.values) == (True, ("SUBP",))
    assert [(a.param, a.extent) for a in call.areas] == [
        (0, "WS-ONE@working_storage[28:32]"),
        (1, "WS-TWO@working_storage[32:36]"),
        (2, "WS-THREE@working_storage[36:40]"),
    ]


def test_an_area_naming_no_field_still_writes_the_jump(out: Path) -> None:
    (link,) = _by_kind(_jumps(out, "PROGA"), JumpKind.LINK)
    assert (link.returns, link.target.values, link.areas) == (True, ("PROGB",), ())


def test_cics_return_start_and_retrieve_are_found_from_their_options(out: Path) -> None:
    rows = _jumps(out, "PROGB")
    (retrieve,) = _by_kind(rows, JumpKind.RETRIEVE)
    (start,) = _by_kind(rows, JumpKind.START)
    (back,) = _by_kind(rows, JumpKind.RETURN_TRANSID)
    assert [a.extent for a in retrieve.areas] == ["WS-Y@working_storage[6:12]"]
    assert (start.transid.values, [a.extent for a in start.areas]) == (
        ("TRNC",),
        ["WS-X@working_storage[0:6]"],
    )
    assert (back.transid.values, [a.extent for a in back.areas]) == (
        ("TRNB",),
        ["DFHCOMMAREA@linkage[0:20]"],
    )


def test_every_program_has_an_entry_row_and_exits_list_received_areas(
    out: Path,
) -> None:
    rows = _jumps(out, "SUBP")
    (entry,) = _by_kind(rows, JumpKind.ENTRY)
    (goback,) = _by_kind(rows, JumpKind.EXIT)
    assert (entry.node, [(a.param, a.fields) for a in entry.areas]) == (
        "",
        [(0, ()), (1, ()), (2, ())],
    )
    assert [
        (a.param, [(f.values, f.writers) for f in a.fields]) for a in goback.areas
    ] == [
        (0, [(("ABCD",), ("MAIN-PARA/0",))]),
        (1, [((), ())]),
        (2, [((), ())]),
    ]


def test_the_existing_tables_are_unchanged(out: Path) -> None:
    assert {name: (out / name).read_text(encoding="utf-8") for name in EXISTING} == {
        name: (BASELINE / name).read_text(encoding="utf-8") for name in EXISTING
    }


def test_an_unsettled_walk_keeps_every_jump_and_marks_its_facts_incomplete(
    out: Path,
) -> None:
    with cached_asg_dialect_parsers_registered():
        asg = CobolASG.from_dict(
            json.loads((out.parent / "parsed" / "PROGA.json").read_text("utf-8"))
        )
    flow, _ = analysed(asg, AnalysisOptions(factor=0))
    by_kind = {jump.kind: jump for jump in flow.jumps}
    incomplete = (UnresolvedReason.INCOMPLETE_WALK,)
    unread = (UnresolvedReason.INCOMPLETE_WALK, UnresolvedReason.UNINITIALISED)
    assert sorted(kind.value for kind in by_kind) == ["CALL", "ENTRY", "LINK", "XCTL"]
    assert by_kind[JumpKind.XCTL].target == Fact(
        extent="WS-NEXT@working_storage[20:28]", reasons=unread
    )
    assert [
        (a.extent, [f.reasons for f in a.fields]) for a in by_kind[JumpKind.XCTL].areas
    ] == [("WS-AREA@working_storage[0:20]", [unread, unread])]
    assert by_kind[JumpKind.CALL].target == Fact(values=("SUBP",), reasons=incomplete)


MENU = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COMM.
           05  WS-COMM-FROM     PIC X(8).
           05  WS-COMM-USER     PIC X(8).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(16).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE DFHCOMMAREA(1:EIBCALEN) TO WS-COMM.
           MOVE 'PROGM' TO WS-COMM-FROM.
           EXEC CICS XCTL PROGRAM('PROGB') COMMAREA(WS-COMM) END-EXEC.
"""


@pytest.mark.xfail(
    reason="partial-overwrite split reverted for unbounded keys; red-dragon-forge-daj",
    strict=True,
)
def test_a_sub_field_overwritten_after_a_record_copy_forgets_the_copy(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path],
) -> None:
    out = fixpoint_corpus({"PROGM": MENU})
    (xctl,) = _by_kind(_jumps(out, "PROGM"), JumpKind.XCTL)
    (area,) = xctl.areas
    assert [(f.extent, f.values, f.writers, f.reasons) for f in area.fields] == [
        ("WS-COMM-FROM@working_storage[0:8]", ("PROGM   ",), ("MAIN-PARA/1",), ()),
        (
            "WS-COMM-USER@working_storage[8:16]",
            (),
            ("MAIN-PARA/0",),
            (UnresolvedReason.INBOUND_LINKAGE,),
        ),
    ]
