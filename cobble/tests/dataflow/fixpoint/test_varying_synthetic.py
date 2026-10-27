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


LENGTHS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VARYLEN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC               PIC X(8).
       01  WS-K                 PIC S9(4) COMP.
       01  WS-START             PIC S9(4) COMP.
       01  WS-STEP              PIC S9(4) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING WS-K FROM LENGTH OF WS-REC BY -1
               UNTIL WS-K < 1
               CONTINUE
           END-PERFORM.
           PERFORM VARYING WS-K FROM WS-START BY WS-STEP
               UNTIL WS-K > 9
               CONTINUE
           END-PERFORM.
           STOP RUN.
"""


def test_a_length_of_bound_reads_no_field_and_a_named_bound_reads_its_field(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    """LENGTH OF is a compile-time constant, so the counter starts from a literal, not
    from a field called "LENGTH OF WS-REC"."""
    edges = {
        (row["attrs"]["node"], row["source"])
        for row in map(
            json.loads,
            (fixpoint_out("VARYLEN", LENGTHS) / "graph.jsonl").read_text().splitlines(),
        )
        if row["type"] == "edge" and row["target"] == "VARYLEN.WS-K"
    }

    assert edges == {
        ("MAIN-PARA/0#init", "VARYLEN.LITERAL"),
        ("MAIN-PARA/0#step", "VARYLEN.WS-K"),
        ("MAIN-PARA/1#init", "VARYLEN.WS-START"),
        ("MAIN-PARA/1#step", "VARYLEN.WS-K"),
        ("MAIN-PARA/1#step", "VARYLEN.WS-STEP"),
    }
