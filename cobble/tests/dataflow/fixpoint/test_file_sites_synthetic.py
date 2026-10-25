"""CICS file statements naming their file through a data item, compiled by the real bridge, resolved."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from cobble.dataflow.combine.cli import cli as combine_cli
from tests.dataflow.combine.corpus_toml import CONFIG
from tests.dataflow.combine.linked_rows import TargetRow, target_rows

SHAPES = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILESHP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG              PIC X.
       01  WS-USRSEC-FILE       PIC X(8) VALUE 'USRSEC  '.
       01  WS-MAYBE-FILE        PIC X(8) VALUE 'ACCTDAT '.
       01  WS-OTHER             PIC X(8).
       01  WS-LONG-NAME         PIC X(12) VALUE 'NOTAFILENAME'.
       01  WS-PGM               PIC X(8) VALUE 'PROGA'.
       01  WS-KEY               PIC X(8).
       01  WS-REC               PIC X(80).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS READ DATASET(WS-USRSEC-FILE) INTO(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS READ FILE('ACCTDAT') INTO(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           IF WS-FLAG = 'Y'
               MOVE WS-OTHER TO WS-MAYBE-FILE
           END-IF.
           EXEC CICS WRITE FILE(WS-MAYBE-FILE) FROM(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS STARTBR FILE(WS-LONG-NAME) RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS XCTL PROGRAM(WS-PGM) END-EXEC.
"""

SENDER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGFA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AREA.
           05  WS-FILE          PIC X(8).
           05  WS-REST          PIC X(12).
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'USRSEC' TO WS-FILE.
           EXEC CICS XCTL PROGRAM('PROGFB') COMMAREA(WS-AREA) END-EXEC.
"""

RECEIVER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGFB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-KEY               PIC X(8).
       01  WS-REC               PIC X(80).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-FILE          PIC X(8).
           05  LK-REST          PIC X(12).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS READ FILE(LK-FILE) INTO(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""

_Shape = tuple[str, str, str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]


def _shapes(rows: list[TargetRow]) -> list[_Shape]:
    return [
        (
            row.node,
            row.kind,
            row.transfer,
            row.expression,
            row.candidates,
            row.reasons,
            row.dropped,
        )
        for row in rows
    ]


def _combined(out: Path, tmp_path: Path) -> Path:
    config = tmp_path / "corpus.toml"
    config.write_text(CONFIG.format(asg=out.parent / "parsed"), encoding="utf-8")
    combined = tmp_path / "combined"
    assert (
        combine_cli(
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
    return combined


def test_a_file_named_by_a_data_item_is_a_site_and_a_literal_file_is_not(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    out = fixpoint_out("FILESHP", SHAPES)

    assert _shapes(target_rows(out / "targets.jsonl")) == [
        ("MAIN-PARA/0", "file", "CICS_READ", "WS-USRSEC-FILE", ("USRSEC",), (), ()),
        (
            "MAIN-PARA/3",
            "file",
            "CICS_WRITE",
            "WS-MAYBE-FILE",
            ("ACCTDAT",),
            ("not-a-literal",),
            (),
        ),
        (
            "MAIN-PARA/4",
            "file",
            "CICS_STARTBR",
            "WS-LONG-NAME",
            (),
            (),
            ("NOTAFILENAME",),
        ),
        ("MAIN-PARA/5", "program", "CICS_XCTL", "WS-PGM", ("PROGA",), (), ()),
    ]


def test_a_file_name_handed_over_in_a_commarea_resolves_through_the_combine(
    fixpoint_corpus: Callable[[Mapping[str, str]], Path], tmp_path: Path
) -> None:
    out = fixpoint_corpus({"PROGFA": SENDER, "PROGFB": RECEIVER})
    combined = _combined(out, tmp_path)

    assert _shapes(target_rows(out / "targets.jsonl")) == [
        (
            "MAIN-PARA/0",
            "file",
            "CICS_READ",
            "LK-FILE",
            (),
            ("inbound-linkage",),
            (),
        )
    ]
    assert _shapes(target_rows(combined / "targets.jsonl")) == [
        ("MAIN-PARA/0", "file", "CICS_READ", "LK-FILE", ("USRSEC",), (), ())
    ]
