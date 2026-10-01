"""Every read defs.jsonl names carries the values it can see, and why they may be short."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

PROGRAM = "READVALS"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READVALS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A                 PIC X(4) VALUE 'AAAA'.
       01  REC.
           05  R-1              PIC X(4).
           05  R-2              PIC X(4).
       01  WS-B                 PIC X(4).
       01  WS-C                 PIC X(8).
       01  WS-D                 PIC X(4).
       01  WS-E                 PIC X(4).
       01  WS-F                 PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-A TO WS-B.
           MOVE 'BBBBCCCC' TO REC.
           MOVE REC TO WS-C.
           EXEC CICS READ FILE('ACCTS') INTO(WS-D) RIDFLD(WS-A)
           END-EXEC.
           MOVE WS-D TO WS-E.
           ACCEPT WS-F.
           MOVE WS-F TO WS-B.
           STOP RUN.
"""


def test_each_read_carries_its_values_and_the_reasons_they_may_be_short(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    rows = [
        json.loads(line)
        for line in (fixpoint_out(PROGRAM, SOURCE) / "defs.jsonl")
        .read_text()
        .splitlines()
    ]

    assert rows == [
        {
            "program": PROGRAM,
            "node": "MAIN-PARA/0",
            "extent": "WS-A@working_storage[0:4]",
            "definers": ["MAIN-PARA/0"],
            "values": ["AAAA"],
            "reasons": [],
        },
        {
            "program": PROGRAM,
            "node": "MAIN-PARA/2",
            "extent": "REC@working_storage[4:12]",
            "definers": ["MAIN-PARA/1"],
            "values": ["BBBBCCCC"],
            "reasons": [],
        },
        {
            "program": PROGRAM,
            "node": "MAIN-PARA/4",
            "extent": "WS-D@working_storage[24:28]",
            "definers": ["MAIN-PARA/3"],
            "values": [],
            "reasons": ["from-file"],
        },
        {
            "program": PROGRAM,
            "node": "MAIN-PARA/6",
            "extent": "WS-F@working_storage[32:36]",
            "definers": ["MAIN-PARA/5"],
            "values": [],
            "reasons": ["uninitialised", "unmodelled"],
        },
    ]
