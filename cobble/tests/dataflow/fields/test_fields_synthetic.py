"""The query surface over a program that was actually compiled from COBOL text.

Everywhere else in this directory the input is an ASG dict or an artefact row,
which keeps the suite fast but leaves one claim untested: that the byte offsets
the queries intersect are the ones a real front end produces. A hand-built extent
agrees with the query by construction. These do not -- the layout here is the
bridge's arithmetic over a source file, so an offset this suite gets wrong is a
failure rather than a fixture.

One JVM parse per artefact, because that is the cost being amortised: each
pipeline runs once, module-scoped, and every test asks a question of the artefact
it wrote. There are two -- one program for the single-member queries, and a caller
and callee pair for the commarea crossing, which cannot be asked of one member.

The layout the source below declares, as the bridge lays it out:

    01 SRC-REC   [0:8]    01 DST-REC  [8:20]    01 SINK   [20:24]
       05 SRC-A  [0:4]       05 DST-A  [8:12]
       05 SRC-B  [4:8]       05 DST-B  [12:16]
    01 ALIAS-REC [0:8]        05 DST-TAIL [16:20]
       05 WHOLE-EIGHT [0:8]

    01 TAB-REC [24:39]                          01 IDX [39:41] COMP
       05 TAB-ENTRY OCCURS 3  [24:29] [29:34] [34:39]
          10 TAB-KEY          [24:26] [29:31] [34:36]
          10 TAB-VAL  COMP-3  [26:29] [31:34] [36:39]
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cobble.dataflow.fields.emit_extents import emit
from cobble.dataflow.fields.extent_text import NO_RANGE, byte_range
from cobble.dataflow.fixpoint.build_corpus import cli
from cobble.dataflow.fixpoint.query import (
    FieldStore,
    Side,
    contributed,
    crossing,
    load,
    reaches,
)

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

PROGRAM = "SYNTHQ"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYNTHQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  SRC-REC.
           05  SRC-A            PIC X(4).
           05  SRC-B            PIC X(4).
       01  ALIAS-REC REDEFINES SRC-REC.
           05  WHOLE-EIGHT      PIC X(8).
       01  DST-REC.
           05  DST-A            PIC X(4).
           05  DST-B            PIC X(4).
           05  DST-TAIL         PIC X(4).
       01  SINK                 PIC X(4).
       01  TAB-REC.
           05  TAB-ENTRY OCCURS 3 TIMES.
               10  TAB-KEY      PIC X(2).
               10  TAB-VAL      PIC S9(5) COMP-3.
       01  IDX                  PIC 9(4) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'AAAA' TO SRC-A.
           MOVE 'BBBB' TO SRC-B.
           MOVE SRC-REC TO DST-REC.
           MOVE DST-A TO SINK.
           MOVE SRC-A TO TAB-KEY (IDX).
           STOP RUN.
"""

GROUP_MOVE = "MAIN-PARA/2"
SINK_MOVE = "MAIN-PARA/3"
SUBSCRIPT_MOVE = "MAIN-PARA/4"


def _bridge_jar() -> Path:
    """The parse is the only stage that needs a JVM, so it is the only thing that
    can make this module unrunnable. A missing JAR is an unbuilt workspace, not a
    failing analysis: ``make jar`` at the root builds it."""
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


def _parsed(workspace: Path) -> Path:
    from cobble.parsing.parse_corpus import Job, parse_one

    source = workspace / "src" / f"{PROGRAM}.cbl"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(SOURCE, encoding="utf-8")

    cache = workspace / "parsed"
    cache.mkdir(parents=True, exist_ok=True)
    result = parse_one(
        Job(source, cache / f"{PROGRAM}.json"), str(_bridge_jar()), (), ("cpy",)
    )

    assert result.ok, result.error
    return cache


def _built(workspace: Path, cache: Path) -> Path:
    out = workspace / "out"
    extents = workspace / "extents.jsonl"
    assert emit(cache, extents, ()) == 0
    assert (
        cli(
            [
                "--asg-dir",
                str(cache),
                "--out-dir",
                str(out),
                "--extents",
                str(extents),
                "--member",
                PROGRAM,
            ]
        )
        == 0
    )
    return out


@pytest.fixture(scope="module")
def artefact(tmp_path_factory) -> Path:
    workspace = tmp_path_factory.mktemp("synthetic")
    return _built(workspace, _parsed(workspace))


@pytest.fixture(scope="module")
def store(artefact: Path) -> FieldStore:
    return load(artefact, artefact.parent / "extents.jsonl")


def _one(store: FieldStore, name: str):
    (found,) = store.field(f"{PROGRAM}.{name}")
    return found


def _flow(store: FieldStore, node: str):
    (found,) = [one for one in store.flows if one.node == node]
    return found


def _range(name: str, low: int, high: int):
    return byte_range(f"{name}@working_storage[{low}:{high}]", PROGRAM)


def test_every_move_in_the_source_produced_an_edge(store):
    """Five MOVEs, five flows. A statement class the transfer layer stops handling
    shows up here as a missing flow rather than as a coverage percentage."""
    assert sorted(one.node for one in store.flows) == [
        "MAIN-PARA/0",
        "MAIN-PARA/1",
        GROUP_MOVE,
        SINK_MOVE,
        SUBSCRIPT_MOVE,
    ]


def test_the_bridges_own_offsets_are_what_the_extents_table_holds(store):
    """The one thing no hand-built fixture can assert: that these are the offsets a
    front end computes, not the ones a test wrote down."""
    assert _one(store, "SRC-REC").ranges == (_range("SRC-REC", 0, 8),)
    assert _one(store, "DST-REC").ranges == (_range("DST-REC", 8, 20),)
    assert _one(store, "DST-B").ranges == (_range("DST-B", 12, 16),)
    assert _one(store, "SINK").ranges == (_range("SINK", 20, 24),)


def test_a_child_written_only_by_a_group_move_still_has_a_writer(store):
    """`MOVE SRC-REC TO DST-REC` names neither DST-A nor DST-B anywhere, so a
    consumer joining on node ids finds no writer for either. This is the reason the
    surface intersects ranges, asserted against a real parse rather than a fixture.
    """
    assert [
        one.node for one in store.touching(_one(store, "DST-A").ranges, Side.TARGET)
    ] == [GROUP_MOVE]
    assert [
        one.node for one in store.touching(_one(store, "DST-B").ranges, Side.TARGET)
    ] == [GROUP_MOVE]
    assert not [one for one in store.flows if one.target.endswith(".DST-A")]


def test_which_bytes_each_child_of_the_group_received_is_recovered(store):
    """The per-child fan-out the emitter no longer writes. DST-A takes SRC-REC's
    first four bytes and DST-B the next four, derived from the two ranges."""
    flow = _flow(store, GROUP_MOVE)

    assert contributed(flow, _one(store, "DST-A").ranges[0]) == _range("SRC-REC", 0, 4)
    assert contributed(flow, _one(store, "DST-B").ranges[0]) == _range("SRC-REC", 4, 8)


def test_the_child_past_the_sources_end_received_spaces_and_not_a_flow(store):
    """DST-REC is twelve bytes and SRC-REC eight, so DST-TAIL is padding. A range
    here would claim source bytes that do not exist."""
    assert contributed(_flow(store, GROUP_MOVE), _one(store, "DST-TAIL").ranges[0]) == (
        NO_RANGE
    )


def test_a_reader_of_the_group_reads_every_field_inside_it(store):
    assert [
        one.node for one in store.touching(_one(store, "SRC-A").ranges, Side.SOURCE)
    ] == [GROUP_MOVE, SUBSCRIPT_MOVE]


def test_a_transitive_walk_crosses_the_group_the_edge_named(store):
    """SRC-A reaches SINK in two hops, and the middle of that path is a field no
    edge names: DST-A is written as part of DST-REC and read on its own."""
    assert reaches(store, _one(store, "SRC-A").ranges, Side.SOURCE, 6) == {
        "SYNTHQ.DST-REC": 1,
        "SYNTHQ.TAB-REC": 1,
        "SYNTHQ.SINK": 2,
    }


def test_the_walk_backwards_from_the_sink_reaches_the_record_it_came_from(store):
    """SRC-REC, the record the statement the walk crossed actually reads.

    Three declared names own those eight bytes and tie on length, so which one the
    endpoint id spells is a tie-break rather than a fact about the bytes. Ranking
    the reference the statement made above the rest is what keeps a consumer joining
    on ids from being handed ALIAS-REC's child, a name this program never moves.
    """
    assert reaches(store, _one(store, "SINK").ranges, Side.TARGET, 6) == {
        "SYNTHQ.DST-A": 1,
        "SYNTHQ.SRC-REC": 2,
    }
    assert _flow(store, GROUP_MOVE).source_text.startswith("SRC-REC@")


def test_every_name_over_the_redefined_record_is_recoverable_from_the_artefact(store):
    """The id the tie-break settled on is one of five owners of those bytes, and a
    reader tracing it gets the rest -- including ALIAS-REC, which ties with SRC-REC
    on level as well as bytes and so is reported by neither direction of
    containment. Asserted against a real parse: the level and the ranges these
    turn on are the bridge's."""
    assert [one.id for one in store.overlapping(_one(store, "SRC-REC").ranges)] == [
        "SYNTHQ.ALIAS-REC",
        "SYNTHQ.SRC-REC",
        "SYNTHQ.SRC-A",
        "SYNTHQ.WHOLE-EIGHT",
        "SYNTHQ.SRC-B",
    ]


def test_a_range_straddling_the_two_records_names_both(store):
    """Bytes 6-10 cross from SRC-REC into DST-REC, so no declared field covers them
    and containment answers nothing in either direction."""
    assert [
        one.id
        for one in store.overlapping((byte_range("?@working_storage[6:10]", PROGRAM),))
    ] == [
        "SYNTHQ.ALIAS-REC",
        "SYNTHQ.SRC-REC",
        "SYNTHQ.WHOLE-EIGHT",
        "SYNTHQ.SRC-B",
        "SYNTHQ.DST-REC",
        "SYNTHQ.DST-A",
    ]


def test_a_record_contains_the_fields_declared_inside_it(store):
    assert [one.id for one in store.contains(_one(store, "DST-REC"))] == [
        "SYNTHQ.DST-A",
        "SYNTHQ.DST-B",
        "SYNTHQ.DST-TAIL",
    ]


def test_a_redefinition_of_a_record_reports_inside_it_and_its_own_level_does_not(store):
    """WHOLE-EIGHT owns bytes SRC-REC owns, at a deeper level, so it is inside it.
    ALIAS-REC owns the same bytes at the same level, and the level is the only
    thing separating a redefining record from the one it redefines."""
    assert [one.id for one in store.contains(_one(store, "SRC-REC"))] == [
        "SYNTHQ.SRC-A",
        "SYNTHQ.WHOLE-EIGHT",
        "SYNTHQ.SRC-B",
    ]


def test_a_table_entrys_field_owns_one_range_per_occurrence(store):
    """OCCURS 3, so three ranges -- and the group holding all three contains it
    while nothing holding only one of them would."""
    assert _one(store, "TAB-KEY").ranges == (
        _range("TAB-KEY", 24, 26),
        _range("TAB-KEY", 29, 31),
        _range("TAB-KEY", 34, 36),
    )
    assert [one.id for one in store.containers(_one(store, "TAB-KEY"))] == [
        "SYNTHQ.TAB-REC",
        "SYNTHQ.TAB-ENTRY",
    ]


def test_a_packed_field_is_published_with_the_usage_that_makes_its_bytes_readable(
    store,
):
    """A partial overlap of a COMP-3 field is not a partial read of its value, so
    the usage has to reach a consumer -- who cannot recompute it from a range."""
    assert _one(store, "TAB-VAL").usage == "COMP-3"
    assert _one(store, "IDX").usage == "COMP"
    assert _one(store, "TAB-KEY").usage == "DISPLAY"


def test_a_computed_subscript_lands_somewhere_in_the_table_and_says_so(store):
    """IDX is not a literal, so the write covers all three occurrences and is
    marked clamped. A consumer reading it as exact would report two occurrences
    overwritten that may not have been."""
    flow = _flow(store, SUBSCRIPT_MOVE)

    assert not flow.target_range.exact
    assert (flow.target_range.start, flow.target_range.end) == (24, 36)
    assert flow.target_text.endswith("~")


def test_a_clamped_target_gives_the_whole_source_rather_than_an_offset(store):
    """Nothing knows which occurrence was written, so nothing can say which of the
    source's bytes a given occurrence received."""
    flow = _flow(store, SUBSCRIPT_MOVE)

    assert contributed(flow, _one(store, "TAB-KEY").ranges[0]) == flow.source_range


def test_the_definers_of_a_group_read_are_the_writes_that_filled_its_children(store):
    """Both literal moves reach the group read, and neither of them names SRC-REC:
    the join is on the range the read covers, so a write to any part of it counts.
    """
    assert store.definers_of(_flow(store, GROUP_MOVE)) == ("MAIN-PARA/0", "MAIN-PARA/1")


def test_the_definer_of_a_child_read_is_the_group_write_that_filled_it(store):
    assert store.definers_of(_flow(store, SINK_MOVE)) == (GROUP_MOVE,)


def test_the_run_settled_and_explained_every_write_it_found(artefact: Path):
    """A synthetic program with no loops has no reason not to settle, and no
    statement class here is one the transfer layer may skip. Either changing is a
    regression this suite should name before a corpus run has to."""
    rows = tuple(
        json.loads(line)
        for line in (artefact.parent / "extents.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert len(rows) == 15
    assert {row["id"] for row in rows} >= {"SYNTHQ.TAB-VAL", "SYNTHQ.ALIAS-REC"}


CALLER = "XPROGA"
CALLEE = "XPROGB"

CALLER_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XPROGA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-OUT-KEY           PIC X(4).
           05  WS-OUT-VAL           PIC X(4).
           05  WS-IN-RESULT         PIC X(4).
       01  WS-SEED                  PIC X(4).
       01  WS-SINK                  PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'KKKK' TO WS-SEED.
           MOVE WS-SEED TO WS-OUT-KEY.
           EXEC CICS LINK PROGRAM('XPROGB')
                          COMMAREA(WS-AREA)
                          LENGTH(12)
           END-EXEC.
           MOVE WS-IN-RESULT TO WS-SINK.
           STOP RUN.
"""

CALLEE_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XPROGB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  SUB-REC.
           05  SUB-KEY              PIC X(4).
           05  SUB-VAL              PIC X(4).
           05  SUB-RESULT           PIC X(4).
       LINKAGE SECTION.
       01  DFHCOMMAREA              PIC X(12).
       PROCEDURE DIVISION.
       SUB-PARA.
           MOVE DFHCOMMAREA TO SUB-REC.
           MOVE SUB-KEY TO SUB-RESULT.
           MOVE SUB-RESULT TO DFHCOMMAREA(9:4).
           EXEC CICS RETURN END-EXEC.
"""
"""The callee writes back through a reference modification rather than repacking
the whole record. A full ``MOVE SUB-REC TO DFHCOMMAREA`` lands on the bytes the
inbound hop already stood on, which the walk's overlap pruning drops -- the same
rule ``reaches`` has always used -- so the return direction would disappear behind
a limitation that has nothing to do with aliases. Both shapes are pinned in
``test_fields_crossing.py``; bead ``nsv`` owns the pruning rule itself."""


@pytest.fixture(scope="module")
def two_program_artefact(tmp_path_factory) -> Path:
    """Parse both members for real, then build all five tables from them."""
    from cobble.parsing.parse_corpus import Job, parse_one

    root = tmp_path_factory.mktemp("crossing")
    cache, out = root / "asg", root / "out"
    cache.mkdir()
    for program, source in ((CALLER, CALLER_SOURCE), (CALLEE, CALLEE_SOURCE)):
        path = root / f"{program}.cbl"
        path.write_text(source, encoding="utf-8")
        result = parse_one(
            Job(path, cache / f"{program}.json"), str(_bridge_jar()), (), ("cpy",)
        )
        assert result.ok, result.error
    extents = root / "extents.jsonl"
    assert emit(cache, extents, ()) == 0
    assert (
        cli(
            [
                "--asg-dir",
                str(cache),
                "--out-dir",
                str(out),
                "--extents",
                str(extents),
                "--all",
            ]
        )
        == 0
    )
    return out


def test_the_alias_row_carries_both_real_layouts(two_program_artefact: Path):
    rows = [
        json.loads(line)
        for line in (two_program_artefact / "aliases.jsonl").read_text().splitlines()
    ]

    (row,) = [one for one in rows if one["callee"] == CALLEE]
    assert row["caller"] == CALLER
    assert row["transfer"] == "LINK"
    assert row["caller_extent"] == "WS-AREA@working_storage[0:12]"
    assert row["callee_extent"] == "DFHCOMMAREA@linkage[0:12]"
    assert row["returns"] is True


def test_a_crossing_query_reaches_the_callee_write_and_comes_back(
    two_program_artefact: Path,
):
    """The whole point: the caller's outbound field crosses in, the callee's write
    crosses back, and the caller's own sink sees it."""
    store = load(two_program_artefact, two_program_artefact.parent / "extents.jsonl")
    (start,) = store.field(f"{CALLER}.WS-OUT-KEY")

    found = crossing(store, start.ranges, Side.SOURCE, depth=6, hops=2)
    landed = {one.field_id: one for one in found.landings}

    assert landed[f"{CALLEE}.SUB-REC"].hops == 1
    assert landed[f"{CALLEE}.SUB-RESULT"].hops == 1
    assert landed[f"{CALLER}.WS-SINK"].hops == 2
    assert landed[f"{CALLER}.WS-SINK"].via == landed[f"{CALLEE}.SUB-REC"].via


def test_the_callee_bytes_are_the_rebased_caller_bytes(two_program_artefact: Path):
    """A name match would get this wrong; a byte rebase does not."""
    store = load(two_program_artefact, two_program_artefact.parent / "extents.jsonl")
    (outbound,) = store.field(f"{CALLER}.WS-OUT-KEY")

    ((_alias, landing),) = store.across(outbound.ranges)

    assert str(landing) == "DFHCOMMAREA@linkage[0:4]"
