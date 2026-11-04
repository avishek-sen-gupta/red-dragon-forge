"""SET condition TO TRUE moves the condition's first value into the field it tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

PROGRAM = "CONDSET"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONDSET.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-P1                PIC X(8) VALUE 'PROGA'.
           88  P1-IS-B          VALUE 'PROGB' 'PROGC'.
       01  GRP-X.
           05  WS-P2            PIC X(8) VALUE 'PROGA'.
               88  PICKED       VALUE 'PROGD'.
       01  GRP-Y.
           05  WS-P3            PIC X(8) VALUE 'PROGA'.
               88  PICKED       VALUE 'PROGE'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET P1-IS-B TO TRUE.
           SET PICKED OF GRP-Y TO TRUE.
           CALL WS-P1.
           CALL WS-P2.
           CALL WS-P3.
           STOP RUN.
"""


def test_set_to_true_moves_the_first_value_into_the_qualified_conditions_field(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    """P1-IS-B has two values and SET moves the first. PICKED is declared twice; OF
    GRP-Y picks the one under WS-P3, and WS-P2 keeps its VALUE."""
    out = fixpoint_out(PROGRAM, SOURCE)
    targets = [
        (row["expression"], row["candidates"], row["reasons"])
        for row in map(json.loads, (out / "targets.jsonl").read_text().splitlines())
    ]

    assert targets == [
        ("WS-P1", ["PROGB"], []),
        ("WS-P2", ["PROGA"], []),
        ("WS-P3", ["PROGE"], []),
    ]
