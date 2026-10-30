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


TWO_CALLERS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFTWO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PGM               PIC X(8) VALUE SPACES.
       01  WS-SEEN              PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'PROGA' TO WS-PGM.
           PERFORM NOTE-PGM.
           MOVE 'PROGB' TO WS-PGM.
           PERFORM NOTE-PGM.
           CALL WS-PGM.
           STOP RUN.
       NOTE-PGM.
           MOVE WS-PGM TO WS-SEEN.
"""


def test_a_performed_paragraph_returns_only_to_the_call_that_entered_it(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    """NOTE-PGM is performed after WS-PGM is set to PROGA and again after PROGB. The
    end of NOTE-PGM returns to both call sites, but each run returns to its own: the
    CALL after the second PERFORM sees only PROGB. Following every return from the
    shared end would carry PROGA back past the second MOVE too."""
    out = fixpoint_out("PERFTWO", TWO_CALLERS)
    targets = [
        (row["expression"], row["candidates"], row["reasons"])
        for row in map(json.loads, (out / "targets.jsonl").read_text().splitlines())
    ]
    seen = [
        (row["definers"], sorted(row["values"]))
        for row in map(json.loads, (out / "defs.jsonl").read_text().splitlines())
        if row["node"] == "NOTE-PGM/0" and row["extent"].startswith("WS-PGM@")
    ]

    assert targets == [("WS-PGM", ["PROGB"], [])]
    assert seen == [(["MAIN-PARA/0", "MAIN-PARA/2"], ["PROGA   ", "PROGB   "])]
