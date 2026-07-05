from __future__ import annotations

import queue
import sqlite3

from cics.types import CicsContext, DispatchKind

from red_dragon_forge.adapters.cics import build_cics_spec
from red_dragon_forge.adapters.sql import build_sql_spec
from interpreter.project.coprocessor_compile import compile_program
from red_dragon_forge.run import run_program
from squall.backends.sqlite import SqliteBackend
from tests.integration.forge_cobol_helpers import make_parser

_COMBINED_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMBINED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID       PIC 9(4) VALUE 42.
       01 WS-BAL      PIC 9(9).
       01 SQLCODE     PIC S9(9).
       01 WS-APPLID   PIC X(8).
       PROCEDURE DIVISION.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           EXEC SQL
               SELECT ACCT_BAL
               INTO :WS-BAL
               FROM ACCOUNT
               WHERE ACCT_ID = :WS-ID
           END-EXEC.
           EXEC CICS ASSIGN APPLID(WS-APPLID)
           END-EXEC.
           EXEC CICS RETURN
           END-EXEC.
"""


def test_cics_and_sql_compose_in_one_program(bridge_jar):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)")
    conn.execute("INSERT INTO ACCOUNT VALUES (42, 777)")
    conn.commit()
    backend = SqliteBackend(conn)

    context_holder = [None]
    result_holder = [None]
    cics_spec = build_cics_spec(
        context_holder=context_holder, result_holder=result_holder, applid="FORGEAPP"
    )
    sql_spec = build_sql_spec(connections={"SAMPLE": backend})
    parser = make_parser(bridge_jar)

    _frontend, linked = compile_program(
        _COMBINED_PROGRAM.encode("utf-8"), parser, [cics_spec, sql_spec]
    )

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    result = run_program(
        linked,
        [cics_spec, sql_spec],
        CicsContext(transid="COMB", commarea=b"", eibaid="\x7d"),
        screen_q,
        input_q,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=10_000,
    )

    assert result.kind == DispatchKind.RETURN
