"""
tests/integration/test_db2_static_e2e.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
First standalone real-code e2e: run an UNMODIFIED IBM db2-samples program
(testbed/db2-samples/cobol_mf/static.sqb) under squall alone.

static.sqb: BEGIN/END DECLARE SECTION, CONNECT TO sample (+ USER/USING + RESET),
and `SELECT FIRSTNME INTO :firstname FROM EMPLOYEE WHERE LASTNAME = 'JOHNSON'`.
The CONNECT/DECLARE directives no-op; the SELECT runs against a SQLite EMPLOYEE
table seeded with the SAMPLE row. Proves squall runs third-party batch DB2 COBOL
end-to-end (the Db2 SAMPLE FIRSTNME for LASTNAME JOHNSON is 'SYBIL').

Requires PROLEAP_BRIDGE_JAR. The Db2 include copybooks (sqlca.cbl / sql.cbl,
normally supplied by Db2) live in tests/integration/db2_includes/.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

_HERE = Path(__file__).parent
_HELPERS = _HERE / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
run_cobol = _helpers.run_cobol
read_ws_field = _helpers.read_ws_field
bridge_jar = _helpers.bridge_jar  # noqa: F401  (re-exported pytest fixture)

from squall.backends.sqlite import SqliteBackend
from squall.strategy import SqlLoweringStrategy

_STATIC_SQB = (
    _HERE.parent.parent / "testbed" / "db2-samples" / "cobol_mf" / "static.sqb"
)
# Db2 include copybooks the sample COPYs: sqlca.cbl is an ALIAS that delegates to
# squall's one canonical SQLCA.cpy (no duplication); sql.cbl is an unused stub.
_DB2_INCLUDES = _HERE / "db2_includes"


def test_static_sqb_runs_standalone(bridge_jar):
    # SAMPLE EMPLOYEE (just the columns static.sqb touches + the JOHNSON row).
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE EMPLOYEE (FIRSTNME VARCHAR(12), LASTNAME VARCHAR(15))")
    conn.executemany(
        "INSERT INTO EMPLOYEE VALUES (?, ?)",
        [("SYBIL", "JOHNSON"), ("CHRISTINE", "HAAS"), ("MICHAEL", "THOMPSON")],
    )

    source = _STATIC_SQB.read_text(encoding="utf-8")
    backend = SqliteBackend(conn)
    vm = run_cobol(
        source,
        bridge_jar,
        extension_strategies=[SqlLoweringStrategy(backend)],
        copybook_dirs=[_DB2_INCLUDES],
        max_steps=8000,
    )

    # SELECT FIRSTNME INTO :firstname WHERE LASTNAME = 'JOHNSON' -> 'SYBIL'.
    # ProLeap preserves source case, so the field key is lowercase 'firstname'
    # (as declared) — matched by the lowercase :firstname host var.
    assert read_ws_field(vm, "firstname") == "SYBIL"
