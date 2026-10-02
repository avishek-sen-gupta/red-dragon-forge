"""A PERFORM VARYING's counter is written by its FROM and its BY, every time round."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

PROGRAM = "VARYPGM"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VARYPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I                 PIC 9(4) VALUE 0.
       01  WS-J                 PIC 9(4) VALUE 0.
       01  WS-B                 PIC 9(4).
       01  WS-C                 PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM USE-I VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3
               AFTER WS-J FROM 1 BY 1 UNTIL WS-J > 2.
           STOP RUN.
       USE-I.
           MOVE WS-I TO WS-B.
           MOVE WS-J TO WS-C.
"""


def test_the_counters_reads_inside_the_loop_see_the_loops_own_writes(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    """Never the VALUE clause: the loop overwrites it before the body first runs."""
    rows = {
        row["extent"].split("@")[0]: (row["definers"], row["values"], row["reasons"])
        for row in map(
            json.loads,
            (fixpoint_out(PROGRAM, SOURCE) / "defs.jsonl").read_text().splitlines(),
        )
    }

    assert rows == {
        "WS-I": (["MAIN-PARA/0#init", "MAIN-PARA/0#step"], [], ["not-a-literal"]),
        "WS-J": (
            ["MAIN-PARA/0.after.0#init", "MAIN-PARA/0.after.0#step"],
            [],
            ["not-a-literal"],
        ),
    }
