"""A statement with no transfer of its own still writes what it names, with doubt."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from cobble.dataflow.fixpoint.member_counts import MemberCounts
from cobble.knowledge_graph.graph_file import read_graph

PROGRAM = "UNMODEL"

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNMODEL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-P1                PIC X(8) VALUE 'PROGA'.
       01  WS-P2                PIC X(8) VALUE 'PROGA'.
       01  WS-P3                PIC X(8) VALUE 'PROGA'.
           88  P3-IS-B          VALUE 'PROGB'.
       01  WS-IN                PIC X(16) VALUE 'PROGC,PROGD'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-P1.
           UNSTRING WS-IN DELIMITED BY ',' INTO WS-P2.
           SET P3-IS-B TO TRUE.
           CALL WS-P1.
           CALL WS-P2.
           CALL WS-P3.
           STOP RUN.
"""


def test_an_unmodelled_write_is_a_definer_a_flow_and_doubt_never_a_proven_target(
    fixpoint_out: Callable[[str, str], Path],
) -> None:
    out = fixpoint_out(PROGRAM, SOURCE)
    targets = [
        (row["expression"], row["candidates"], row["reasons"])
        for row in map(json.loads, (out / "targets.jsonl").read_text().splitlines())
    ]
    _, edges = read_graph(out / "graph.jsonl")
    counts = MemberCounts.model_validate_json(
        (out / "members" / PROGRAM / "counts.json").read_text()
    )

    assert targets == [
        ("WS-P1", ["PROGA"], ["unmodelled"]),
        ("WS-P2", ["PROGA"], ["unmodelled"]),
        ("WS-P3", ["PROGA"], ["unmodelled"]),
    ]
    assert sorted((edge.source, edge.target) for edge in edges) == [
        ("UNMODEL.UNMODELLED:ACCEPT", "UNMODEL.WS-P1"),
        ("UNMODEL.UNMODELLED:SET", "UNMODEL.WS-P3"),
        ("UNMODEL.WS-IN", "UNMODEL.WS-P2"),
    ]
    assert (counts.writes, counts.covered, counts.unmodelled) == (3, 3, 3)
