"""End-to-end integration test: EXEC SQL SELECT INTO on a real VM.

Compiles a real COBOL program through the real CobolFrontend (ProLeap bridge
JAR), runs the resulting IR on the real RedDragon VMState, and asserts on
working-storage fields decoded from the post-run memory region.

This test exercises the full squall runtime stack end-to-end:
  ProLeap bridge → CobolFrontend + SqlLoweringStrategy → __exec_sql builtin
  → SqliteBackend → write_outputs / write_sqlcode → WS region bytes.

A green test that short-circuits any of these layers (fake VM, stubbed
frontend, IR-only assertions) is a failure here.

Notes:
  - SQLCA / SQLCODE: slice 1 does not implement EXEC SQL INCLUDE SQLCA
    END-EXEC expansion, so SQLCODE is declared as a plain field:
        01 SQLCODE PIC S9(9).
    This is a deliberate slice-1 limitation.
  - The bridge JAR path is read from PROLEAP_BRIDGE_JAR env (fail-fast,
    no default, no skip).  Run with:
        PROLEAP_BRIDGE_JAR=.../proleap-bridge.jar uv run python -m pytest tests/integration -q
  - The bridge_jar fixture is defined in conftest.py in this directory.
"""

from __future__ import annotations

import sqlite3

import pytest

# ── Import helpers without clashing with vendor/red-dragon/tests/integration ──
# vendor/red-dragon appears before squall's root in sys.path (editable install),
# so "from tests.integration.X import ..." resolves to the vendor's package.
# We use importlib to load squall's own helpers by filesystem path instead.
import importlib.util
import pathlib

_HELPERS_PATH = pathlib.Path(__file__).parent / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS_PATH)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)

run_cobol = _helpers.run_cobol
read_ws_field = _helpers.read_ws_field

from squall.backends.sqlite import SqliteBackend

# ---------------------------------------------------------------------------
# COBOL program under test
# ---------------------------------------------------------------------------

# Slice-1 note: SQLCODE is declared inline as a plain field because EXEC SQL
# INCLUDE SQLCA END-EXEC expansion is not yet implemented.  The builtin writes
# to a field literally named "SQLCODE" in the WS layout.
_COBOL_SELECT_INTO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID  PIC 9(4) VALUE 11.
       01 WS-BAL PIC 9(9).
       01 SQLCODE PIC S9(9).
       PROCEDURE DIVISION.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           EXEC SQL
               SELECT ACCT_BAL
               INTO :WS-BAL
               FROM ACCOUNT
               WHERE ACCT_ID = :WS-ID
           END-EXEC.
           STOP RUN.
"""


# ---------------------------------------------------------------------------
# SQLite seed helpers
# ---------------------------------------------------------------------------


def _make_backend(acct_id: int, acct_bal: int) -> SqliteBackend:
    """Return an in-memory SqliteBackend seeded with one ACCOUNT row."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)")
    conn.execute("INSERT INTO ACCOUNT VALUES (?, ?)", (acct_id, acct_bal))
    conn.commit()
    return SqliteBackend(conn)


def _make_backend_empty() -> SqliteBackend:
    """Return an in-memory SqliteBackend with an empty ACCOUNT table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)")
    conn.commit()
    return SqliteBackend(conn)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_select_into_hit(bridge_jar):
    """SELECT INTO with a matching row writes WS-BAL=500 and SQLCODE=0."""
    backend = _make_backend(acct_id=11, acct_bal=500)

    vm = run_cobol(
        _COBOL_SELECT_INTO,
        bridge_jar_path=bridge_jar,
        connections={"SAMPLE": backend},
        max_steps=2000,
    )

    ws_bal = read_ws_field(vm, "WS-BAL")
    sqlcode = read_ws_field(vm, "SQLCODE")

    assert ws_bal == 500, f"Expected WS-BAL=500, got {ws_bal!r}"
    assert sqlcode == 0, f"Expected SQLCODE=0, got {sqlcode!r}"


def test_select_into_no_row(bridge_jar):
    """SELECT INTO with no matching row sets SQLCODE=100; WS-BAL is unchanged (0)."""
    backend = _make_backend_empty()

    vm = run_cobol(
        _COBOL_SELECT_INTO,
        bridge_jar_path=bridge_jar,
        connections={"SAMPLE": backend},
        max_steps=2000,
    )

    ws_bal = read_ws_field(vm, "WS-BAL")
    sqlcode = read_ws_field(vm, "SQLCODE")

    assert sqlcode == 100, f"Expected SQLCODE=100, got {sqlcode!r}"
    assert ws_bal == 0, f"Expected WS-BAL unchanged (0), got {ws_bal!r}"
