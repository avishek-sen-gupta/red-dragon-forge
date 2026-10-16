"""The load-bearing proof for task 10 (2026-09-19-carddemo-db2-tier): an
abending task actually rolls back its Db2 unit of work through the exact
wiring forge-run's [cics] mode uses with [sql] --
``on_abend=backend.rollback`` supplied to ``build_cics_spec`` (Task 6's
seam).

Before Task 6, SYNCPOINT was a no-op, XCTL fired no rollback hook, and an
abend told squall nothing -- a suite that only asserted through the
program's own Db2Backend connection could not tell a real rollback from one
that never happened, since both leave that same connection's session
looking identical afterwards. This test asserts through db2_probe_conn, a
completely separate connection, which is the only way to actually
distinguish "committed" from "uncommitted-then-abandoned".

Round-1 review fix: the original version of this test asserted "row absent
on db2_probe_conn" WITHOUT ever committing the program's own connection.
That assertion cannot fail -- db2_probe_conn is a separate session and
therefore can never see conn's uncommitted work, whether that work was
genuinely rolled back, never rolled back (on_abend a no-op), or never even
executed. The fix is the explicit ``ibm_db.commit(conn)`` below: if
backend.rollback already ended the unit of work, that commit flushes
nothing; if it did not (or was never wired), the still-pending INSERT
commits and the row appears. Verified by execution: temporarily removing
``on_abend=backend.rollback`` from ``_run`` below makes this test fail (row
'99' is 1, not 0) -- see task-10-report.md. Removing the explicit commit
instead does NOT make it fail; it reverts to the original bug -- the
assertion becomes unable to fail either way, which is exactly the defect
this fix addresses, not a second way to catch one.

The mirror ``test_task_return_commits_the_db2_insert`` below is the positive
control: without it, "row absent" in the abend test is also consistent with
the INSERT never having reached the backend at all (this program declares
``01 SQLCODE PIC S9(9)`` directly rather than COPYing SQLCA, and the SQL
runtime runs ``tolerant=True``, so a misrouted statement would silently no-op
rather than fail compilation).

Composes build_cics_spec/build_sql_spec/install_sql_runtime directly (the
same calls a forge-build and forge-run make) against an inline synthetic
program, rather than going through a package, so this stays a focused test of
the rollback mechanism itself; forge-run's OWN wiring of on_abend is covered
separately by tests/unit/test_cics_sql_wiring.py.
"""

from __future__ import annotations

import queue

import ibm_db
import pytest
from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.transaction_hooks import TransactionHooks
from cics.types import CicsContext, DispatchKind
from interpreter.project.coprocessor_compile import compile_program
from squall.backends.db2 import Db2Backend
from squall.connector import NamedDbConnector
from squall.coprocessor import build_sql_spec
from squall.runtime import install_sql_runtime

from cobol_harness.compile import main_entry
from red_dragon_forge.run import run_program
from tests.integration.forge_cobol_helpers import make_parser

_ABEND_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DB2ABND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 SQLCODE     PIC S9(9).
       PROCEDURE DIVISION.
           EXEC SQL
               INSERT INTO CARDDEMO.TRANSACTION_TYPE
                   (TR_TYPE, TR_DESCRIPTION)
               VALUES ('99', 'ROLLBACK-TEST')
           END-EXEC.
           EXEC CICS ABEND ABCODE('TEST')
           END-EXEC.
"""

_RETURN_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DB2RTRN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 SQLCODE     PIC S9(9).
       PROCEDURE DIVISION.
           EXEC SQL
               INSERT INTO CARDDEMO.TRANSACTION_TYPE
                   (TR_TYPE, TR_DESCRIPTION)
               VALUES ('98', 'COMMIT-TEST')
           END-EXEC.
           EXEC CICS RETURN
           END-EXEC.
"""


def _run(program_source: str, transid: str, bridge_jar: str, dsn: str):
    """Compose cics+squall exactly as forge-run does (backend.rollback
    as on_abend) and run *program_source* to completion. Returns the
    DispatchResult and the program's own (still open) connection -- the
    caller decides what to do with it."""
    conn = ibm_db.connect(dsn, "", "")
    backend = Db2Backend(conn)  # autocommit OFF from here on

    context_holder = [None]
    result_holder = [None]
    sql = install_sql_runtime(
        {"CARDDEMO": backend},
        NamedDbConnector("CARDDEMO"),
        tolerant=True,
    )
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        result_holder=result_holder,
        on_abend=backend.rollback,
        hooks=TransactionHooks(sql.reset_session, sql.syncpoint, sql.rollback),
        other_builtins=sql.entries,
    )
    cics_spec = build_cics_spec()
    sql_spec = build_sql_spec()
    parser = make_parser(bridge_jar)

    linked = compile_program(
        program_source.encode("utf-8"), parser, [cics_spec, sql_spec]
    )

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    result = run_program(
        linked,
        [cics_spec, sql_spec],
        CicsContext(transid=transid, commarea=b"", eibaid="\x7d"),
        screen_q,
        input_q,
        entry=main_entry(linked),
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=10_000,
        builtins=runtime.builtins,
    )
    return result, conn


def _count(conn, tr_type: str) -> int:
    stmt = ibm_db.exec_immediate(
        conn,
        f"SELECT COUNT(*) FROM CARDDEMO.TRANSACTION_TYPE WHERE TR_TYPE = '{tr_type}'",
    )
    row = ibm_db.fetch_tuple(stmt)  # type: ignore[reportArgumentType]
    # ibm_db's stub types fetch_tuple()'s row as tuple[object, ...] -- the
    # driver returns real Python ints for an integer column in practice (see
    # squall.backends.db2's own docstring on this exact stub boundary).
    return int(tuple(row)[0])  # type: ignore[reportArgumentType]


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_task_abend_rolls_back_an_uncommitted_db2_insert(
    bridge_jar, db2_dsn, db2_probe_conn
):
    """Verified by execution -- and verified to actually fail without the
    fix: temporarily removing ``on_abend=backend.rollback`` from the
    composition in ``_run`` above makes this test see TR_TYPE '99'
    committed (1, not 0), since ``make_abend_builtin`` (cics/builtins/system.py)
    only ever calls ``on_abend`` on the abend path -- there is no other
    commit or rollback in play."""
    result, conn = _run(_ABEND_PROGRAM, "DBAB", bridge_jar, db2_dsn)
    try:
        assert result.kind == DispatchKind.ABEND
        # The crux of the fix: flush conn's own session. If backend.rollback
        # already ended the unit of work, this commits nothing. If it did
        # not (on_abend removed/no-op), the still-pending INSERT commits
        # here, and the assertion below then sees it and fails.
        ibm_db.commit(conn)  # type: ignore[reportArgumentType]
    finally:
        ibm_db.close(conn)  # type: ignore[reportArgumentType]

    assert _count(db2_probe_conn, "99") == 0


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_task_return_commits_the_db2_insert(bridge_jar, db2_dsn, db2_probe_conn):
    """Positive control. EXEC CICS RETURN's task-end hook commits
    (squall.builtins.exec_sql._end_of_uow via _reset_session), so this
    otherwise-identical program must leave its row visible -- proving the
    INSERT above genuinely reaches the backend, which is what makes the
    abend test's "row absent" meaningful rather than vacuous."""
    result, conn = _run(_RETURN_PROGRAM, "DBRT", bridge_jar, db2_dsn)
    try:
        assert result.kind == DispatchKind.RETURN
    finally:
        ibm_db.close(conn)  # type: ignore[reportArgumentType]

    assert _count(db2_probe_conn, "98") == 1
