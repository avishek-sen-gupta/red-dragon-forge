from __future__ import annotations

import queue
import sqlite3

from cics.types import CicsContext, DispatchKind

from cics.coprocessor import build_cics_spec
from squall.coprocessor import build_sql_spec
from squall.runtime import install_sql_runtime
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
        transid_to_program={},
        program_cache={},
        context_holder=context_holder,
        result_holder=result_holder,
        applid="FORGEAPP",
    )
    sql_spec = build_sql_spec()
    parser = make_parser(bridge_jar)

    linked = compile_program(
        _COMBINED_PROGRAM.encode("utf-8"), parser, [cics_spec, sql_spec]
    )
    install_sql_runtime({"SAMPLE": backend})

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


_CURSOR_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CURSORPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME     PIC X(9).
       01 WS-DEPT     PIC 9(4).
       01 SQLCODE     PIC S9(9).
       PROCEDURE DIVISION.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           EXEC SQL DECLARE C1 CURSOR FOR
               SELECT NAME, DEPT FROM STAFF WHERE JOB = 'Mgr'
           END-EXEC
           EXEC SQL OPEN C1 END-EXEC
           EXEC SQL FETCH C1 INTO :WS-NAME, :WS-DEPT END-EXEC
           EXEC CICS RETURN
           END-EXEC.
"""


def test_cics_return_resets_the_sql_session_end_to_end(bridge_jar):
    """The task-end hook cicada's RETURN lowering calls and squall's strategy
    registers under (__cics_task_end_hook) are never referenced directly by
    either package — this is the only test that actually runs a compiled
    program through both strategies and checks the wire-up did its job: a
    cursor left open by an EXEC CICS RETURN is closed, not leaked into the
    next task."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE STAFF (NAME VARCHAR(9), DEPT INTEGER, JOB VARCHAR(5))")
    conn.execute("INSERT INTO STAFF VALUES ('SANDERS', 20, 'Mgr')")
    conn.commit()
    backend = SqliteBackend(conn)

    context_holder = [None]
    result_holder = [None]
    cics_spec = build_cics_spec(
        transid_to_program={},
        program_cache={},
        context_holder=context_holder,
        result_holder=result_holder,
        applid="FORGEAPP",
    )
    sql_spec = build_sql_spec()
    parser = make_parser(bridge_jar)

    linked = compile_program(
        _CURSOR_PROGRAM.encode("utf-8"), parser, [cics_spec, sql_spec]
    )
    install_sql_runtime({"SAMPLE": backend})

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    result = run_program(
        linked,
        [cics_spec, sql_spec],
        CicsContext(transid="CURS", commarea=b"", eibaid="\x7d"),
        screen_q,
        input_q,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=10_000,
    )

    assert result.kind == DispatchKind.RETURN
    # The FETCH above proves the cursor really was open; if RETURN's task-end
    # hook never reached squall, it would still be registered here.
    assert backend._cursors == {}
