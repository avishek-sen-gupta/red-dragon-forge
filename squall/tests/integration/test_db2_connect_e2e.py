"""
tests/integration/test_db2_connect_e2e.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Faithful CONNECT against TWO real Db2 databases (squall-yml, Task 5).

A program CONNECTs to the logical name DBA (→ MOJO), inserts a row, CONNECTs to
DBB (→ MOJO2), inserts another, then CONNECT RESET and one final INSERT that must
report SQLCODE -1024 (no connection). We verify each row landed in the right
database and the disconnected statement reached no backend.

A second program proves CONNECT TO an unregistered name surfaces -1013 through the
full stack.

Requires PROLEAP_BRIDGE_JAR and two live Db2 databases via SQUALL_DB2_DSN
(MOJO) and SQUALL_DB2_DSN2 (MOJO2). No skip, fail loud.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_HERE = Path(__file__).parent
_HELPERS = _HERE / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
run_cobol = _helpers.run_cobol
read_ws_field = _helpers.read_ws_field
bridge_jar = _helpers.bridge_jar  # noqa: F401  (re-exported pytest fixture)

from squall.backends.db2 import Db2Backend

pytestmark = pytest.mark.db2

_DB2_INCLUDES = _HERE / "db2_includes"

# Logical CONNECT names (DBA/DBB) are registry keys, not physical db names — the
# registry decouples the COBOL CONNECT target from the pre-established connection.
_ROUTING_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONNE2E.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01 WS-RC PIC S9(9) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL CONNECT TO DBA END-EXEC
           EXEC SQL INSERT INTO ROUTED VALUES (111) END-EXEC
           EXEC SQL CONNECT TO DBB END-EXEC
           EXEC SQL INSERT INTO ROUTED VALUES (222) END-EXEC
           EXEC SQL CONNECT RESET END-EXEC
           EXEC SQL INSERT INTO ROUTED VALUES (999) END-EXEC
           MOVE SQLCODE TO WS-RC.
           STOP RUN.
"""

_UNKNOWN_DB_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONNBAD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01 WS-RC PIC S9(9) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL CONNECT TO NOSUCHDB END-EXEC
           MOVE SQLCODE TO WS-RC.
           STOP RUN.
"""


def _setup_routed(conn) -> None:
    import ibm_db

    try:
        ibm_db.exec_immediate(conn, "DROP TABLE ROUTED")
    except Exception:  # noqa: BLE001 — table may not exist yet
        pass
    ibm_db.exec_immediate(conn, "CREATE TABLE ROUTED (ID INTEGER)")
    ibm_db.commit(conn)


def _count(conn, value: int) -> int:
    import ibm_db

    stmt = ibm_db.exec_immediate(
        conn, f"SELECT COUNT(*) FROM ROUTED WHERE ID = {value}"
    )
    ibm_db.fetch_row(stmt)
    return int(ibm_db.result(stmt, 0))


def _drop(conn) -> None:
    import ibm_db

    try:
        ibm_db.exec_immediate(conn, "DROP TABLE ROUTED")
        ibm_db.commit(conn)
    except Exception:  # noqa: BLE001
        pass


def test_connect_routes_between_two_db2_databases(bridge_jar):
    import ibm_db

    ca = ibm_db.connect(os.environ["SQUALL_DB2_DSN"], "", "")
    cb = ibm_db.connect(os.environ["SQUALL_DB2_DSN2"], "", "")
    try:
        _setup_routed(ca)
        _setup_routed(cb)

        vm = run_cobol(
            _ROUTING_PROGRAM,
            bridge_jar,
            connections={"DBA": Db2Backend(ca), "DBB": Db2Backend(cb)},
            copybook_dirs=[_DB2_INCLUDES],
            max_steps=4000,
        )

        # 111 routed to DBA (MOJO) only; 222 to DBB (MOJO2) only.
        assert _count(ca, 111) == 1 and _count(ca, 222) == 0
        assert _count(cb, 222) == 1 and _count(cb, 111) == 0
        # The INSERT after CONNECT RESET reached no connection.
        assert read_ws_field(vm, "WS-RC") == -1024
        assert _count(ca, 999) == 0 and _count(cb, 999) == 0
    finally:
        _drop(ca)
        _drop(cb)
        ibm_db.close(ca)
        ibm_db.close(cb)


def test_connect_to_unknown_db_reports_minus_1013(bridge_jar):
    import ibm_db

    ca = ibm_db.connect(os.environ["SQUALL_DB2_DSN"], "", "")
    try:
        vm = run_cobol(
            _UNKNOWN_DB_PROGRAM,
            bridge_jar,
            connections={"SAMPLE": Db2Backend(ca)},
            copybook_dirs=[_DB2_INCLUDES],
            max_steps=2000,
        )
        assert read_ws_field(vm, "WS-RC") == -1013
    finally:
        ibm_db.close(ca)
