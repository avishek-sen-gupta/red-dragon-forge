"""The return-to-caller idiom, compiled by the real bridge, linked end to end."""

from collections.abc import Callable, Mapping
from pathlib import Path

from cobble.dataflow.combine.asg_callee_areas import AsgCalleeAreas
from cobble.dataflow.combine.cli import cli
from cobble.dataflow.combine.load import load_tables
from cobble.dataflow.combine.table_callee_areas import TableCalleeAreas
from cobble.dataflow.fields.extent_text import byte_range
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


def test_the_areas_taken_from_the_tables_equal_the_ones_read_from_the_parse_cache(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path],
) -> None:
    out = fixpoint_corpus({"PROGA": PROGA, "PROGB": PROGB})
    asg = AsgCalleeAreas(out.parent / "parsed")
    tables = {name: load_tables(out, name) for name in ("PROGA", "PROGB")}
    from_tables = TableCalleeAreas(tables, asg)

    assert [from_tables.area(name, JumpKind.XCTL, 0) for name in tables] == [
        asg.area(name, JumpKind.XCTL, 0) for name in tables
    ]
    assert [str(from_tables.area(name, JumpKind.XCTL, 0)) for name in tables] == [
        "DFHCOMMAREA@linkage[0:20]",
        "DFHCOMMAREA@linkage[0:20]",
    ]
