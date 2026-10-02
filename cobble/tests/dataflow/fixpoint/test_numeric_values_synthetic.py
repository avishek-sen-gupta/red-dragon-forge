"""A numeric VALUE is imaged as its digits where text can hold it, and not at all
where it cannot."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

PROGRAM = "NUMVALS"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMVALS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N                 PIC 9(4) VALUE 0.
       01  WS-D                 PIC 9(3)V99 VALUE 12.5.
       01  WS-S                 PIC S9(3) VALUE 7.
       01  WS-Z                 PIC 9(4) VALUE ZERO.
       01  WS-NEG               PIC S9(3) VALUE -7.
       01  WS-C                 PIC S9(4) COMP VALUE 5.
       01  WS-P                 PIC S9(5) COMP-3 VALUE 5.
       01  WS-OUT               PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-N TO WS-OUT.
           MOVE WS-D TO WS-OUT.
           MOVE WS-S TO WS-OUT.
           MOVE WS-Z TO WS-OUT.
           MOVE WS-NEG TO WS-OUT.
           MOVE WS-C TO WS-OUT.
           MOVE WS-P TO WS-OUT.
           STOP RUN.
"""


def test_a_numeric_value_is_its_digits_or_nothing(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    """Unsigned and positive zoned decimal read back as right-justified, zero-filled
    digits. A negative zoned value, COMP and COMP-3 have no faithful text form, so
    no value is claimed for them."""
    values = {
        row["extent"].split("@")[0]: row["values"]
        for row in map(
            json.loads,
            (fixpoint_out(PROGRAM, SOURCE) / "defs.jsonl").read_text().splitlines(),
        )
    }

    assert values == {
        "WS-N": ["0000"],
        "WS-D": ["01250"],
        "WS-S": ["007"],
        "WS-Z": ["0000"],
        "WS-NEG": [],
        "WS-C": [],
        "WS-P": [],
    }
