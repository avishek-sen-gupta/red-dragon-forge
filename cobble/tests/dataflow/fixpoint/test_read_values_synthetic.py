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
            "definers": [],
            "values": ["AAAA"],
            "reasons": [],
            "kind": "copied",
        },
        {
            "program": PROGRAM,
            "node": "MAIN-PARA/2",
            "extent": "REC@working_storage[4:12]",
            "definers": ["MAIN-PARA/1"],
            "values": ["BBBBCCCC"],
            "reasons": [],
            "kind": "copied",
        },
        {
            "program": PROGRAM,
            "node": "MAIN-PARA/3",
            "extent": "WS-A@working_storage[0:4]",
            "definers": [],
            "values": ["AAAA"],
            "reasons": [],
            "kind": "consulted",
        },
        {
            "program": PROGRAM,
            "node": "MAIN-PARA/4",
            "extent": "WS-D@working_storage[24:28]",
            "definers": ["MAIN-PARA/3"],
            "values": [],
            "reasons": ["from-file"],
            "kind": "copied",
        },
        {
            "program": PROGRAM,
            "node": "MAIN-PARA/6",
            "extent": "WS-F@working_storage[32:36]",
            "definers": ["MAIN-PARA/5"],
            "values": [],
            "reasons": ["uninitialised", "unmodelled"],
            "kind": "copied",
        },
    ]


READS = "READSALL"

READS_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READSALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN                PIC X(4).
       01  WS-COPY              PIC X(4).
       01  WS-KEY               PIC X(4) VALUE 'ABCD'.
       01  WS-ARG               PIC X(4) VALUE 'ARG1'.
       01  WS-REC               PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-IN.
           MOVE WS-IN TO WS-COPY.
           IF WS-COPY = 'STOP'
               STOP RUN
           END-IF.
           EXEC CICS READ FILE('ACCTS') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           CALL 'SUBPGM' USING WS-ARG.
           STOP RUN.
"""


def test_a_test_operand_and_a_ridfld_get_consulted_rows_and_a_call_argument_none(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    rows = [
        json.loads(line)
        for line in (fixpoint_out(READS, READS_SOURCE) / "defs.jsonl")
        .read_text()
        .splitlines()
    ]

    assert rows == [
        {
            "program": READS,
            "node": "MAIN-PARA/1",
            "extent": "WS-IN@working_storage[0:4]",
            "definers": ["MAIN-PARA/0"],
            "values": [],
            "reasons": ["uninitialised", "unmodelled"],
            "kind": "copied",
        },
        {
            "program": READS,
            "node": "MAIN-PARA/2#test",
            "extent": "WS-COPY@working_storage[4:8]",
            "definers": ["MAIN-PARA/1"],
            "values": [],
            "reasons": ["uninitialised", "unmodelled"],
            "kind": "consulted",
        },
        {
            "program": READS,
            "node": "MAIN-PARA/3",
            "extent": "WS-KEY@working_storage[8:12]",
            "definers": [],
            "values": ["ABCD"],
            "reasons": [],
            "kind": "consulted",
        },
    ]


PERFORMED = "READPERF"

PERFORMED_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READPERF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FLAG              PIC X(1).
       01  WS-OUT               PIC X(1).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'Y' TO WS-FLAG.
           PERFORM CHECK-PARA.
           STOP RUN.
       CHECK-PARA.
           IF WS-FLAG = 'Y'
               MOVE 'X' TO WS-OUT
           END-IF.
"""


def test_a_test_inside_a_performed_paragraph_sees_what_was_written_before_the_call(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    rows = [
        json.loads(line)
        for line in (fixpoint_out(PERFORMED, PERFORMED_SOURCE) / "defs.jsonl")
        .read_text()
        .splitlines()
    ]

    assert rows == [
        {
            "program": PERFORMED,
            "node": "CHECK-PARA/0#test",
            "extent": "WS-FLAG@working_storage[0:1]",
            "definers": ["MAIN-PARA/0"],
            "values": ["Y"],
            "reasons": [],
            "kind": "consulted",
        },
    ]
