"""A STRING whose sending is an intrinsic FUNCTION reads the function's arguments, and
no field named after the function."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRFN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                 PIC X(8).
       01  WS-Y                 PIC X(4).
       01  WS-OUT               PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STRING FUNCTION TRIM(WS-X) WS-Y
               DELIMITED BY SIZE INTO WS-OUT.
           STOP RUN.
"""


def test_a_function_sending_reads_its_arguments(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    sources = {
        row["source"]
        for row in map(
            json.loads,
            (fixpoint_out("STRFN", SOURCE) / "graph.jsonl").read_text().splitlines(),
        )
        if row["type"] == "edge" and row["target"] == "STRFN.WS-OUT"
    }

    assert sources == {"STRFN.WS-X", "STRFN.WS-Y"}
