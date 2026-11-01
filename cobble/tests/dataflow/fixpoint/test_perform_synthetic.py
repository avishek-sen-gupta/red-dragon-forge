"""What a performed paragraph writes is what the statement after the PERFORM sees."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
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


def test_a_sweep_budget_returns_each_perform_to_its_own_caller_too(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
) -> None:
    """--sweeps bounds the same walk the worklist runs, so a budget large enough to
    settle gives the worklist's answer: the CALL after the second PERFORM sees only
    PROGB, and NOTE-PGM still sees both values, one from each call."""
    out = fixpoint_corpus_with({"PERFTWO": TWO_CALLERS}, ("--sweeps", "5"))
    targets = [
        (row["expression"], row["candidates"], row["reasons"])
        for row in map(json.loads, (out / "targets.jsonl").read_text().splitlines())
    ]
    seen = [
        (row["definers"], sorted(row["values"]))
        for row in map(json.loads, (out / "defs.jsonl").read_text().splitlines())
        if row["node"] == "NOTE-PGM/0" and row["extent"].startswith("WS-PGM@")
    ]
    counts = json.loads((out / "members" / "PERFTWO" / "counts.json").read_text())

    assert targets == [("WS-PGM", ["PROGB"], [])]
    assert seen == [(["MAIN-PARA/0", "MAIN-PARA/2"], ["PROGA   ", "PROGB   "])]
    assert counts["settled"] is True


LOOP_INSIDE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFLOOP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC X(8) VALUE 'PROGA'.
       01  WS-B                 PIC X(8) VALUE SPACES.
       01  WS-C                 PIC X(8) VALUE SPACES.
       01  WS-N                 PIC 9(2) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM OUTER.
           CALL WS-C.
           STOP RUN.
       OUTER.
           PERFORM BODY UNTIL WS-N > 3.
       BODY.
           MOVE WS-B TO WS-C.
           MOVE WS-A TO WS-B.
           ADD 1 TO WS-N.
"""


def test_a_sweep_budget_bounds_the_walks_inside_a_perform_and_says_so(
    fixpoint_corpus_with: Callable[[Mapping[str, str], tuple[str, ...]], Path],
) -> None:
    """MAIN-PARA has no loop of its own: the loop is inside OUTER. One pass of each
    walk cannot carry BODY's write of WS-B round to the read before it, so with
    --sweeps 1 the CALL misses PROGA and the member is unsettled, and a budget that
    lets OUTER's walk go round settles with PROGA found."""
    one = fixpoint_corpus_with({"PERFLOOP": LOOP_INSIDE}, ("--sweeps", "1"))
    enough = fixpoint_corpus_with({"PERFLOOP": LOOP_INSIDE}, ("--sweeps", "5"))

    def target(out: Path) -> tuple[list[str], bool]:
        row = json.loads((out / "targets.jsonl").read_text().splitlines()[0])
        counts = json.loads((out / "members" / "PERFLOOP" / "counts.json").read_text())
        return row["candidates"], counts["settled"]

    assert target(one) == ([], False)
    assert target(enough) == (["PROGA"], True)
