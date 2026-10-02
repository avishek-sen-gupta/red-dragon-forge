"""What a performed paragraph writes is what the statement after the PERFORM sees."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

PROGRAM = "PERFPGM"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM               PIC X(8) VALUE 'PROGA'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SET-PGM.
           CALL WS-PGM.
           STOP RUN.
       SET-PGM.
           MOVE 'PROGB' TO WS-PGM.
"""


def test_a_performed_paragraph_cannot_be_skipped(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    """SET-PGM always runs, so the VALUE it overwrites never reaches the CALL."""
    rows = [
        (row["expression"], row["candidates"], row["reasons"])
        for row in map(
            json.loads,
            (fixpoint_out(PROGRAM, SOURCE) / "targets.jsonl").read_text().splitlines(),
        )
    ]

    assert rows == [("WS-PGM", ["PROGB"], [])]
