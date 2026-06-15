"""
tests/integration/test_db2_cursor_e2e.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Cursors, all the way through, against REAL Db2: run the unmodified IBM
db2-samples cursor.sqb on the live MOJO instance.

cursor.sqb: DECLARE c1 CURSOR FOR SELECT name, dept FROM staff WHERE job='Mgr'
-> OPEN c1 -> (PERFORM FETCH c1 INTO :pname,:dept UNTIL SQLCODE <> 0) -> CLOSE c1.
Each fetched manager is DISPLAYed; we capture stdout and assert the managers
appear and the non-manager does not. Requires PROLEAP_BRIDGE_JAR and a live Db2
via SQUALL_DB2_DSN (no skip, fail loud).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_HERE = Path(__file__).parent
_HELPERS = _HERE / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
run_cobol = _helpers.run_cobol
bridge_jar = _helpers.bridge_jar  # noqa: F401  (re-exported pytest fixture)

from squall.backends.db2 import Db2Backend

_CURSOR_SQB = (
    _HERE.parent.parent / "testbed" / "db2-samples" / "cobol_mf" / "cursor.sqb"
)
_DB2_INCLUDES = _HERE / "db2_includes"

_STAFF = [
    (10, "SANDERS", 20, "Mgr"),
    (30, "MARENGHI", 38, "Mgr"),
    (40, "NGAN", 15, "Clerk"),  # excluded by WHERE job='Mgr'
]


def test_cursor_sqb_runs_against_db2(bridge_jar, capsys):
    import ibm_db

    conn = ibm_db.connect(os.environ["SQUALL_DB2_DSN"], "", "")

    def _silent(sql):
        try:
            ibm_db.exec_immediate(conn, sql)
        except Exception:
            pass

    try:
        _silent("DROP TABLE STAFF")
        ibm_db.exec_immediate(
            conn,
            "CREATE TABLE STAFF (ID SMALLINT, NAME VARCHAR(9), DEPT SMALLINT, JOB CHAR(5))",
        )
        for sid, name, dept, job in _STAFF:
            ibm_db.exec_immediate(
                conn, f"INSERT INTO STAFF VALUES ({sid}, '{name}', {dept}, '{job}')"
            )
        ibm_db.commit(conn)

        backend = Db2Backend(conn)
        run_cobol(
            _CURSOR_SQB.read_text(encoding="utf-8"),
            bridge_jar,
            backend=backend,
            copybook_dirs=[_DB2_INCLUDES],
            max_steps=8000,
        )

        # The FETCH loop DISPLAYs each manager (and only managers).
        out = capsys.readouterr().out
        assert "SANDERS" in out, out
        assert "MARENGHI" in out, out
        assert "NGAN" not in out  # the clerk was filtered by the cursor's WHERE
    finally:
        _silent("DROP TABLE STAFF")
        ibm_db.commit(conn)
        ibm_db.close(conn)
