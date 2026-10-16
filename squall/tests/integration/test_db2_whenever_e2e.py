"""
tests/integration/test_db2_whenever_e2e.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
EXEC SQL WHENEVER SQLERROR GO TO against REAL Db2. A SELECT from a non-existent
table fails (SQLCODE < 0); the active WHENEVER must branch to the handler, which
sets a flag we read back. (No standalone testbed program exercises WHENEVER GOTO
— outsrv.sqb is a stored-procedure server — so this uses a focused program.)
Requires PROLEAP_BRIDGE_JAR and a live Db2 via SQUALL_DB2_DSN (no skip, fail loud).
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

_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. WHENE2E.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01 WS-FLAG PIC X VALUE "N".
       01 WS-VAL  PIC S9(4) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           EXEC SQL WHENEVER SQLERROR GO TO ERR-PARA END-EXEC
           EXEC SQL SELECT 1 INTO :WS-VAL FROM NOSUCHTABLEXYZ END-EXEC
           MOVE "T" TO WS-FLAG.
           STOP RUN.
       ERR-PARA.
           MOVE "E" TO WS-FLAG.
           STOP RUN.
"""


def test_whenever_sqlerror_branches_to_handler(bridge_jar):
    import ibm_db

    conn = ibm_db.connect(os.environ["SQUALL_DB2_DSN"], "", "")
    try:
        vm = run_cobol(
            _PROGRAM,
            bridge_jar,
            connections={"SAMPLE": Db2Backend(conn)},
            copybook_dirs=[_DB2_INCLUDES],
            max_steps=4000,
        )
        # The SELECT failed (-204); WHENEVER branched to ERR-PARA (flag 'E').
        # Without the branch, control would fall through to 'T'.
        assert read_ws_field(vm, "WS-FLAG") == "E"
    finally:
        ibm_db.close(conn)
