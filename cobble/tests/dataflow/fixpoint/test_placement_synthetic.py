"""Where a move's source bytes land in its target, compiled by the real bridge: byte copies are
placed, conversions and composed writes are not."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from cobble.dataflow.fixpoint.provenance import provenance

PROGRAM = "PLACED"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PLACED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC X(10).
       01  WS-B                 PIC X(10).
       01  WS-SMALL             PIC 9(4)V99.
       01  WS-BIG               PIC 9(9)V99.
       01  WS-BIN               PIC 9(4) COMP.
       01  WS-DISP              PIC 999.
       01  WS-EDIT              PIC ZZZ9.99.
       01  WS-GRP.
           05  WS-G1            PIC X(4).
           05  WS-G2            PIC 9(4).
       01  WS-COPY              PIC X(8).
       01  WS-CODE              PIC X(2).
       01  WS-NUM               PIC 9(4).
       01  WS-INT               PIC 9(4).
       01  WS-S1                PIC S9(4)V99.
       01  WS-S2                PIC S9(5)V9.
       01  WS-OUT               PIC X(12).
       01  WS-RJ                PIC X(6) JUSTIFIED RIGHT.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-A(4:3) TO WS-B.
           MOVE WS-SMALL TO WS-BIG.
           MOVE WS-BIG TO WS-SMALL.
           MOVE WS-BIN TO WS-DISP.
           MOVE WS-SMALL TO WS-EDIT.
           MOVE WS-GRP TO WS-COPY.
           MOVE WS-CODE TO WS-NUM.
           MOVE WS-INT TO WS-A.
           MOVE WS-S1 TO WS-S2.
           STRING WS-A(1:3) '-' DELIMITED BY SIZE INTO WS-OUT.
           COMPUTE WS-BIG = WS-SMALL + 1.
           MOVE WS-CODE TO WS-RJ.
           MOVE WS-S1 TO WS-B.
           ADD WS-SMALL TO WS-BIG.
           STOP RUN.
"""


def test_a_move_says_where_its_source_bytes_land_only_when_it_copies_them(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    """An alphanumeric or group copy lands left-aligned from the bytes actually read;
    display numerics line up on the decimal point, text into an unsigned display number
    on its units digit, and text into a JUSTIFIED RIGHT receiver on its right. Binary to
    display, numeric to edited, a change of scale under a sign, a signed number into text,
    STRING and COMPUTE rewrite the bytes, so they say nowhere; STRING, COMPUTE and ADD are
    marked rebuilt: they build the target's value in place."""
    landed = {
        (dep.site.rsplit("/", 1)[1], dep.source.name, dep.target.name): (
            dep.landing,
            dep.rebuilt,
        )
        for dep in provenance(fixpoint_out(PROGRAM, SOURCE))
        if dep.source.known and dep.target.known
    }

    assert landed == {
        ("0", "WS-A", "WS-B"): ((0,), False),
        ("1", "WS-SMALL", "WS-BIG"): ((5,), False),
        ("2", "WS-BIG", "WS-SMALL"): ((-5,), False),
        ("3", "WS-BIN", "WS-DISP"): ((), False),
        ("4", "WS-SMALL", "WS-EDIT"): ((), False),
        ("5", "WS-GRP", "WS-COPY"): ((0,), False),
        ("6", "WS-CODE", "WS-NUM"): ((2,), False),
        ("7", "WS-INT", "WS-A"): ((0,), False),
        ("8", "WS-S1", "WS-S2"): ((), False),
        ("9", "WS-A", "WS-OUT"): ((), True),
        ("10", "WS-SMALL", "WS-BIG"): ((), True),
        ("11", "WS-CODE", "WS-RJ"): ((4,), False),
        ("12", "WS-S1", "WS-B"): ((), False),
        ("13", "WS-SMALL", "WS-BIG"): ((), True),
        ("13", "WS-BIG", "WS-BIG"): ((), True),
    }
