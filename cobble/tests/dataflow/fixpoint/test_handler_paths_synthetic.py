"""A paragraph reached only through HANDLE CONDITION is part of the program analysed."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from cobble.knowledge_graph.graph_file import read_graph

PROGRAM = "HANDLER"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HANDLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-KEY               PIC X(8).
       01  WS-REC               PIC X(20).
       01  WS-MSG               PIC X(20) VALUE 'RECORD NOT FOUND'.
       01  WS-OUT               PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS HANDLE CONDITION NOTFND(NOT-FOUND) END-EXEC.
           EXEC CICS READ FILE('ACCTS') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           MOVE WS-REC TO WS-OUT.
           GOBACK.
       NOT-FOUND.
           MOVE WS-MSG TO WS-OUT.
           GOBACK.
"""


def test_the_handler_paragraph_a_raise_reaches_contributes_its_flows(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    """NOT-FOUND follows a GOBACK, so only the READ's raise reaches it."""
    _, edges = read_graph(fixpoint_out(PROGRAM, SOURCE) / "graph.jsonl")

    assert sorted((edge.source, edge.target) for edge in edges) == [
        ("HANDLER.FILE:ACCTS", "HANDLER.WS-REC"),
        ("HANDLER.WS-MSG", "HANDLER.WS-OUT"),
        ("HANDLER.WS-REC", "HANDLER.WS-OUT"),
    ]
