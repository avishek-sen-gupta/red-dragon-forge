"""The return-to-caller idiom, compiled by the real bridge, linked end to end."""

import logging
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from cobble.dataflow.combine.asg_callee_areas import AsgCalleeAreas
from cobble.dataflow.combine.cli import cli
from cobble.dataflow.combine.load import load_tables
from cobble.dataflow.combine.table_callee_areas import TableCalleeAreas
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fixpoint.query import cli as query_cli
from cobble.dataflow.fixpoint.query import load_for
from cobble.dataflow.jumps.jump_kind import JumpKind
from tests.dataflow.combine.corpus_toml import CONFIG
from tests.dataflow.combine.linked_rows import (
    LinkRow,
    TargetRow,
    link_rows,
    target_rows,
)

PROGA = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-FROM          PIC X(8).
           05  WS-REST          PIC X(12).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGA' TO WS-FROM.
           EXEC CICS XCTL PROGRAM('PROGB') COMMAREA(WS-AREA) END-EXEC.
"""

PROGB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NEXT              PIC X(8).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-FROM          PIC X(8).
           05  LK-REST          PIC X(12).
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF LK-FROM = SPACES
               MOVE 'PROGM' TO WS-NEXT
           ELSE
               MOVE LK-FROM TO WS-NEXT
           END-IF.
           EXEC CICS XCTL PROGRAM(WS-NEXT)
               COMMAREA(DFHCOMMAREA) END-EXEC.
"""


def test_return_to_caller_links_end_to_end(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path], tmp_path: Path
) -> None:
    out = fixpoint_corpus({"PROGA": PROGA, "PROGB": PROGB})
    config = tmp_path / "corpus.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"), encoding="utf-8")
    combined = tmp_path / "combined"

    assert (
        cli(
            [
                "--config",
                str(config),
                "--fixpoint-dir",
                str(out),
                "--out-dir",
                str(combined),
                "--all",
            ]
        )
        == 0
    )

    assert target_rows(out / "targets.jsonl") == [
        TargetRow(
            caller="PROGB",
            node="MAIN-PARA/1",
            transfer="CICS_XCTL",
            expression="WS-NEXT",
            candidates=("PROGM",),
            reasons=("inbound-linkage",),
            dropped=(),
        )
    ]
    assert target_rows(combined / "targets.jsonl") == [
        TargetRow(
            caller="PROGB",
            node="MAIN-PARA/1",
            transfer="CICS_XCTL",
            expression="WS-NEXT",
            candidates=("PROGA", "PROGM"),
            reasons=(),
            dropped=(),
            outside=(),
        )
    ]
    assert link_rows(combined / "links.jsonl") == [
        LinkRow(
            caller="PROGA",
            node="MAIN-PARA/1",
            transfer="XCTL",
            callee="PROGB",
            caller_extent="WS-AREA@working_storage[0:20]",
            callee_extent="DFHCOMMAREA@linkage[0:20]",
            returns=False,
            reason="",
            discovered=False,
        ),
        LinkRow(
            caller="PROGB",
            node="MAIN-PARA/1",
            transfer="XCTL",
            callee="PROGA",
            caller_extent="DFHCOMMAREA@linkage[0:20]",
            callee_extent="DFHCOMMAREA@linkage[0:20]",
            returns=False,
            reason="",
            discovered=True,
        ),
    ]


def test_links_let_the_provenance_query_cross_a_discovered_jump(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path], tmp_path: Path
) -> None:
    out = fixpoint_corpus({"PROGA": PROGA, "PROGB": PROGB})
    config = tmp_path / "corpus.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"), encoding="utf-8")
    combined = tmp_path / "combined"
    cli(
        [
            "--config",
            str(config),
            "--fixpoint-dir",
            str(out),
            "--out-dir",
            str(combined),
            "--all",
        ]
    )
    extents = out.parent / "extents.jsonl"
    from_b = byte_range("DFHCOMMAREA@linkage[0:20]", "PROGB")

    plain = load_for(out, extents, "PROGB.DFHCOMMAREA")
    linked = load_for(out, extents, "PROGB.DFHCOMMAREA", combined / "links.jsonl")

    assert [a.callee for a, _ in plain.across((from_b,))] == []
    assert [(a.callee, str(landed)) for a, landed in linked.across((from_b,))] == [
        ("PROGA", "DFHCOMMAREA@linkage[0:20]")
    ]


def test_the_areas_taken_from_the_tables_equal_the_ones_read_once_from_the_parse_cache(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path],
) -> None:
    out = fixpoint_corpus({"PROGA": PROGA, "PROGB": PROGB})
    asg = AsgCalleeAreas(out.parent / "parsed")
    tables = {name: load_tables(out, name) for name in ("PROGA", "PROGB")}
    from_tables = TableCalleeAreas(tables, asg)
    outside = TableCalleeAreas({}, asg)
    first = outside.area("PROGA", JumpKind.XCTL, 0)
    (out.parent / "parsed" / "PROGA.json").unlink()

    assert [from_tables.area(name, JumpKind.XCTL, 0) for name in tables] == [
        asg.area(name, JumpKind.XCTL, 0) for name in tables
    ]
    assert [str(from_tables.area(name, JumpKind.XCTL, 0)) for name in tables] == [
        "DFHCOMMAREA@linkage[0:20]",
        "DFHCOMMAREA@linkage[0:20]",
    ]
    assert (str(first), str(outside.area("PROGA", JumpKind.LINK, 0))) == (
        "DFHCOMMAREA@linkage[0:20]",
        "DFHCOMMAREA@linkage[0:20]",
    )


PROGM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SRC               PIC X(8) VALUE 'PROGA'.
       01  WS-I                 PIC 9.
       01  WS-TBL.
           05  WS-EL            PIC X(8) OCCURS 3.
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-SRC TO WS-EL(1).
           MOVE 'PROGB' TO WS-EL(2).
           MOVE DFHCOMMAREA TO WS-EL(3).
           EXEC CICS XCTL PROGRAM(WS-EL(WS-I))
               COMMAREA(WS-TBL) END-EXEC.
"""

PROGN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGB.
       DATA DIVISION.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-EL1           PIC X(8).
           05  LK-REST          PIC X(16).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS XCTL PROGRAM(LK-EL1) END-EXEC.
"""


def test_a_subscripted_target_keeps_its_doubt_and_pins_no_occurrence(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path], tmp_path: Path
) -> None:
    out = fixpoint_corpus({"PROGM": PROGM, "PROGB": PROGN})
    config = tmp_path / "corpus.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"), encoding="utf-8")
    combined = tmp_path / "combined"

    assert (
        cli(
            [
                "--config",
                str(config),
                "--fixpoint-dir",
                str(out),
                "--out-dir",
                str(combined),
                "--all",
            ]
        )
        == 0
    )

    assert target_rows(combined / "targets.jsonl") == [
        TargetRow(
            caller="PROGB",
            node="MAIN-PARA/0",
            transfer="CICS_XCTL",
            expression="LK-EL1",
            candidates=("PROGA",),
            reasons=(),
            dropped=(),
            outside=(),
        ),
        TargetRow(
            caller="PROGM",
            node="MAIN-PARA/3",
            transfer="CICS_XCTL",
            expression="WS-EL(WS-I)",
            candidates=("PROGA", "PROGB"),
            reasons=("inbound-linkage",),
            dropped=(),
            outside=(),
        ),
    ]


def test_the_query_command_reads_links_in_place_of_aliases(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = fixpoint_corpus({"PROGA": PROGA, "PROGB": PROGB})
    config = tmp_path / "corpus.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"), encoding="utf-8")
    combined = tmp_path / "combined"
    linked = cli(
        [
            "--config",
            str(config),
            "--fixpoint-dir",
            str(out),
            "--out-dir",
            str(combined),
            "--all",
        ]
    )
    assert linked == 0
    query = [
        "reaches",
        "PROGB.DFHCOMMAREA",
        "--fixpoint-dir",
        str(out),
        "--extents",
        str(out.parent / "extents.jsonl"),
        "--across-calls",
        "--max-hops",
        "2",
    ]
    capsys.readouterr()

    assert query_cli(query) == 0
    plain = capsys.readouterr().out
    assert query_cli([*query, "--links", str(combined / "links.jsonl")]) == 0
    linked = capsys.readouterr().out

    heading = (
        "PROGB.DFHCOMMAREA  level 01  usage DISPLAY\n"
        "  declared at DFHCOMMAREA@linkage[0:20]\n"
    )
    assert plain == (
        heading
        + "flows into across calls (depth 6, max 2 hops, 1 landings):\n"
        + "  hop 0  depth 1  PROGB.WS-NEXT  WS-NEXT@working_storage[0:8]\n\n"
    )
    assert linked == (
        heading
        + "flows into across calls (depth 6, max 2 hops, 2 landings):\n"
        + "  hop 0  depth 1  PROGB.WS-NEXT  WS-NEXT@working_storage[0:8]\n"
        + "  hop 1  depth 1  PROGA.DFHCOMMAREA  DFHCOMMAREA@linkage[0:20]"
        + "  via PROGB:MAIN-PARA/1\n\n"
    )


PROGX = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGX.
       DATA DIVISION.
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS RETURN END-EXEC.
"""


def test_a_link_combine_discovers_into_another_group_is_warned_and_counted(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PROGB's own walk names only PROGM, so PROGX starts in a group of its own;
    combine then finds PROGA handing PROGB the name PROGX."""
    out = fixpoint_corpus(
        {
            "PROGA": PROGA.replace("'PROGA' TO WS-FROM", "'PROGX' TO WS-FROM"),
            "PROGB": PROGB,
            "PROGX": PROGX,
        }
    )
    config = tmp_path / "corpus.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"), encoding="utf-8")
    caplog.set_level(logging.INFO)

    code = cli(
        [
            "--config",
            str(config),
            "--fixpoint-dir",
            str(out),
            "--out-dir",
            str(tmp_path / "combined"),
            "--all",
        ]
    )

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("cobble.dataflow.combine.cli")
    ]
    assert code == 0
    assert [m for m in messages if "group" in m] == [
        "combine: 2 call groups, the largest 2 programs",
        "combine: !! PROGB MAIN-PARA/1 links to PROGX, outside its call group",
        "combine: links that crossed call groups: 1",
    ]
    assert [
        (row.caller, row.callee, row.discovered)
        for row in link_rows(tmp_path / "combined" / "links.jsonl")
    ] == [
        ("PROGA", "PROGB", False),
        ("PROGB", "PROGX", True),
    ]
