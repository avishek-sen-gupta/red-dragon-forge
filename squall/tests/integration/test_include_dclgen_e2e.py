"""End-to-end integration test: EXEC SQL INCLUDE SQLCA + DCLGEN COMP-3 SELECT INTO.

Compiles a real COBOL program through the real CobolFrontend (ProLeap bridge
JAR), runs the resulting IR on the real RedDragon VMState, and asserts on
working-storage fields decoded from the post-run memory region.

This test exercises the full squall slice-2 stack end-to-end:
  apply_sql_prepass (EXEC SQL INCLUDE → COPY) → ProLeap (COPY inlined from
  squall.copybooks) → CobolFrontend + SqlLoweringStrategy → __exec_sql builtin
  → SqliteBackend → write_outputs (COMP-3/BINARY/ALPHA encode) → WS bytes →
  RedDragon VM decodes ACCT-BAL as COMP-3 and compares to 1234.56 →
  IF branch sets WS-FLAG='Y'.

Key assertion:
  WS-FLAG == 'Y' — proves RedDragon's own COMP-3 decoder accepted the bytes
  squall wrote into ACCT-BAL.  A test that re-reads ACCT-BAL through squall's
  _comp3_decode would not prove this; only the IF inside the COBOL program can.

The bridge JAR path is read from PROLEAP_BRIDGE_JAR env (fail-fast, no
default, no skip).  Run with:
    PROLEAP_BRIDGE_JAR=.../proleap-bridge.jar uv run python -m pytest tests/integration -q
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

# EXEC SQL INCLUDE SQLCA / ACCTREC are rewritten by apply_sql_prepass to
# COPY SQLCA. / COPY ACCTREC., which ProLeap inlines from squall.copybooks.
# After the SELECT INTO, the COBOL IF compares ACCT-BAL (COMP-3) to the
# numeric literal 1234.56 — the VM decodes squall's packed bytes natively.
_COBOL_INCLUDE_DCLGEN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DCLGNTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID   PIC 9(4) VALUE 11.
       01 WS-FLAG PIC X    VALUE 'N'.
       EXEC SQL INCLUDE SQLCA END-EXEC.
       EXEC SQL INCLUDE ACCTREC END-EXEC.
       PROCEDURE DIVISION.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           EXEC SQL
               SELECT ACCT_ID, ACCT_BAL, ACCT_NAME
               INTO :ACCT-ID, :ACCT-BAL, :ACCT-NAME
               FROM ACCOUNT WHERE ACCT_ID = :WS-ID
           END-EXEC.
           IF ACCT-BAL = 1234.56
               MOVE 'Y' TO WS-FLAG
           ELSE
               MOVE 'N' TO WS-FLAG
           END-IF.
           STOP RUN.
"""


# ---------------------------------------------------------------------------
# SQLite seed helpers
# ---------------------------------------------------------------------------


def _make_backend_hit() -> SqliteBackend:
    """Return an in-memory SqliteBackend seeded with ACCOUNT row (11, 1234.56, ALICE)."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL NUMERIC, ACCT_NAME TEXT)"
    )
    conn.execute("INSERT INTO ACCOUNT VALUES (?, ?, ?)", (11, 1234.56, "ALICE"))
    conn.commit()
    return SqliteBackend(conn)


def _make_backend_miss() -> SqliteBackend:
    """Return an in-memory SqliteBackend with an empty ACCOUNT table."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL NUMERIC, ACCT_NAME TEXT)"
    )
    conn.commit()
    return SqliteBackend(conn)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_include_dclgen_hit(bridge_jar):
    """SELECT INTO with a matching row:
    - WS-FLAG == 'Y' (RedDragon decoded squall's COMP-3 bytes correctly)
    - SQLCODE == 0
    - ACCT-NAME == 'ALICE'
    """
    backend = _make_backend_hit()

    vm = run_cobol(
        _COBOL_INCLUDE_DCLGEN,
        bridge_jar_path=bridge_jar,
        connections={"SAMPLE": backend},
        max_steps=2000,
    )

    ws_flag = read_ws_field(vm, "WS-FLAG")
    sqlcode = read_ws_field(vm, "SQLCODE")
    acct_name = read_ws_field(vm, "ACCT-NAME")

    # Key assertion: the COBOL IF branch set WS-FLAG='Y', which means RedDragon's
    # own COMP-3 decoder accepted the bytes squall wrote for 1234.56.
    assert (
        ws_flag == "Y"
    ), f"Expected WS-FLAG='Y' (RedDragon decoded COMP-3 1234.56 correctly), got {ws_flag!r}"
    assert sqlcode == 0, f"Expected SQLCODE=0, got {sqlcode!r}"
    assert (
        acct_name is not None and acct_name.rstrip() == "ALICE"
    ), f"Expected ACCT-NAME='ALICE', got {acct_name!r}"


def test_include_dclgen_miss(bridge_jar):
    """SELECT INTO with no matching row (WS-ID=99):
    - SQLCODE == 100 (NOT FOUND)
    - WS-FLAG stays 'N' (the ACCT-BAL = 1234.56 branch is not taken)
    """
    backend = _make_backend_miss()

    # Override WS-ID inline: use a COBOL program with WS-ID VALUE 99.
    cobol_miss = _COBOL_INCLUDE_DCLGEN.replace(
        "01 WS-ID   PIC 9(4) VALUE 11.", "01 WS-ID   PIC 9(4) VALUE 99."
    )

    vm = run_cobol(
        cobol_miss,
        bridge_jar_path=bridge_jar,
        connections={"SAMPLE": backend},
        max_steps=2000,
    )

    ws_flag = read_ws_field(vm, "WS-FLAG")
    sqlcode = read_ws_field(vm, "SQLCODE")

    assert sqlcode == 100, f"Expected SQLCODE=100 (NOT FOUND), got {sqlcode!r}"
    assert (
        ws_flag == "N"
    ), f"Expected WS-FLAG='N' (no row → IF not taken), got {ws_flag!r}"
