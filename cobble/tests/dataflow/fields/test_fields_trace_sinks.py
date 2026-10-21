"""cobble-fields-trace records where bytes leave the program, compiled by the real bridge.

TSINK writes a record area to a sequential file, a field to a CICS file, a map's
symbolic output record to the terminal, an item to a TS queue, a line to a TD
queue, and data to a started transaction. Each output is a dep row from the field
that went out to the sink, its definers the statement that last wrote those bytes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cobble.dataflow.fields.trace import Budget, Trace, sampled

FORGE = Path(__file__).resolve().parents[4]
BRIDGE_GLOB = "vendor/red-dragon/proleap-bridge/target/proleap-bridge-*-shaded.jar"

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TSINK.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUTF ASSIGN TO OUTDD.
       DATA DIVISION.
       FILE SECTION.
       FD  OUTF.
       01  OUT-REC              PIC X(8).
       WORKING-STORAGE SECTION.
       01  WS-REC               PIC X(8).
       01  WS-KEY               PIC X(4).
       01  MAP1O                PIC X(8).
       01  WS-ITEM              PIC X(4).
       01  WS-LINE              PIC X(4).
       01  WS-DATA              PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'AAAAAAAA' TO WS-REC.
           OPEN OUTPUT OUTF.
           WRITE OUT-REC FROM WS-REC.
           EXEC CICS WRITE FILE('KSDS') FROM(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           MOVE WS-REC TO MAP1O.
           EXEC CICS SEND MAP('MAP1') MAPSET('SET1') END-EXEC.
           MOVE 'IIII' TO WS-ITEM.
           EXEC CICS WRITEQ TS QUEUE('Q1') FROM(WS-ITEM) END-EXEC.
           MOVE 'LLLL' TO WS-LINE.
           EXEC CICS WRITEQ TD QUEUE('CSSL') FROM(WS-LINE) END-EXEC.
           MOVE 'DDDD' TO WS-DATA.
           EXEC CICS START TRANSID('T001') FROM(WS-DATA) END-EXEC.
           CLOSE OUTF.
           GOBACK.
"""


def _bridge_jar() -> Path:
    found = sorted(FORGE.glob(BRIDGE_GLOB))
    if not found:
        pytest.skip(f"no bridge JAR at {BRIDGE_GLOB}; run `make jar`")
    return found[-1]


@pytest.fixture(scope="module")
def traced(tmp_path_factory) -> Trace:
    from cobble.parsing.parse_corpus import Job, parse_one

    root = tmp_path_factory.mktemp("trace-sinks")
    cache = root / "asg"
    cache.mkdir()
    path = root / "TSINK.cbl"
    path.write_text(PROGRAM, encoding="utf-8")
    result = parse_one(
        Job(path, cache / "TSINK.json"), str(_bridge_jar()), (), ("cpy",)
    )
    assert result.ok, result.error
    return sampled("TSINK", cache, Budget(paths=2))


def test_every_output_is_a_row_from_the_field_that_went_out_to_its_sink(
    traced: Trace,
) -> None:
    assert {
        (dep.node, dep.source.field_name, dep.sink, dep.definers)
        for dep in traced.deps
        if dep.sink
    } == {
        ("MAIN-PARA/2", "OUT-REC", "FILE:OUTF", ("TSINK/MAIN-PARA/2",)),
        ("MAIN-PARA/3", "WS-REC", "FILE:KSDS", ("TSINK/MAIN-PARA/0",)),
        ("MAIN-PARA/5", "MAP1O", "MAP:MAP1", ("TSINK/MAIN-PARA/4",)),
        ("MAIN-PARA/7", "WS-ITEM", "TSQ:Q1", ("TSINK/MAIN-PARA/6",)),
        ("MAIN-PARA/9", "WS-LINE", "TDQ:CSSL", ("TSINK/MAIN-PARA/8",)),
        ("MAIN-PARA/11", "WS-DATA", "TRANSID:T001", ("TSINK/MAIN-PARA/10",)),
    }
