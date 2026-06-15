"""
tests/integration/test_db2_transactions.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
EXEC SQL ROLLBACK against REAL Db2, driven by the unmodified IBM db2-samples
``updat.sqb``: it UPDATEs every Mgr to Clerk, DELETEs all Clerks, INSERTs a row,
then ROLLBACKs the whole unit of work. We seed STAFF, run it, and assert every
change was undone — proving Db2Backend keeps autocommit OFF so the program owns
the transaction boundary.

Requires PROLEAP_BRIDGE_JAR and a live Db2 via SQUALL_DB2_DSN (no skip, fail loud).
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
from squall.strategy import SqlLoweringStrategy

_UPDAT = _HERE.parent.parent / "testbed" / "db2-samples" / "cobol_mf" / "updat.sqb"
_DB2_INCLUDES = _HERE / "db2_includes"

# updat.sqb's INSERT is VALUES (999, 'Testing', 99, :job, 0, 0, 0) — 7 columns.
_STAFF_DDL = (
    "CREATE TABLE STAFF (ID SMALLINT, NAME VARCHAR(9), DEPT SMALLINT, "
    "JOB CHAR(5), YEARS SMALLINT, SALARY DECIMAL(7,2), COMM DECIMAL(7,2))"
)
_SEED = [
    "INSERT INTO STAFF VALUES (10, 'SANDERS', 20, 'Mgr', 7, 18357.50, 0)",
    "INSERT INTO STAFF VALUES (40, 'NGAN', 15, 'Clerk', 5, 12508.20, 206.60)",
]


def _query1(conn, sql):
    import ibm_db

    stmt = ibm_db.exec_immediate(conn, sql)
    ibm_db.fetch_row(stmt)
    return ibm_db.result(stmt, 0)


def test_updat_sqb_rolls_back_every_change(bridge_jar):
    import ibm_db

    conn = ibm_db.connect(os.environ["SQUALL_DB2_DSN"], "", "")

    def _silent(sql):
        try:
            ibm_db.exec_immediate(conn, sql)
        except Exception:
            pass

    try:
        # Seed BEFORE Db2Backend flips autocommit off, so the seed is committed.
        _silent("DROP TABLE STAFF")
        ibm_db.exec_immediate(conn, _STAFF_DDL)
        for ins in _SEED:
            ibm_db.exec_immediate(conn, ins)
        ibm_db.commit(conn)

        backend = Db2Backend(conn)  # autocommit now OFF — the program owns the txn
        run_cobol(
            _UPDAT.read_text(encoding="utf-8"),
            bridge_jar,
            extension_strategies=[SqlLoweringStrategy(backend)],
            copybook_dirs=[_DB2_INCLUDES],
            max_steps=20000,
        )

        # ROLLBACK undid the UPDATE (the Mgr is still a Mgr), the DELETE (the Clerk
        # is still present), and the INSERT (the test row 999 never persisted).
        assert (
            str(_query1(conn, "SELECT JOB FROM STAFF WHERE ID = 10")).strip() == "Mgr"
        )
        assert int(_query1(conn, "SELECT COUNT(*) FROM STAFF WHERE ID = 40")) == 1
        assert int(_query1(conn, "SELECT COUNT(*) FROM STAFF WHERE ID = 999")) == 0
    finally:
        ibm_db.rollback(conn)
        _silent("DROP TABLE STAFF")
        ibm_db.commit(conn)
        ibm_db.close(conn)
