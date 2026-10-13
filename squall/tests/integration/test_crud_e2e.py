"""
tests/integration/test_crud_e2e.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The capstone (squall-swd): the whole vertical on a GENERATED copybook.

  dclgen(schema) -> ACCTREC.cpy
       -> EXEC SQL INCLUDE ACCTREC  (apply_sql_prepass rewrites to COPY)
       -> ProLeap inlines it -> lower -> compile -> link
       -> run on the real VMState performing INSERT / SELECT / UPDATE / SELECT /
          DELETE / SELECT against real SQLite, with SQLCODE checks.

No hand-written copybook: the host-var record is produced by squall.dclgen from
the live table schema. Requires PROLEAP_BRIDGE_JAR (the build-product JAR).
"""

from __future__ import annotations

import importlib.util
import sqlite3
from decimal import Decimal
from pathlib import Path

# Load the integration helpers by path (vendor/red-dragon shadows the
# `tests` package name on sys.path, so a plain import won't resolve).
_HELPERS = Path(__file__).parent / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
run_cobol = _helpers.run_cobol
read_ws_field = _helpers.read_ws_field
bridge_jar = _helpers.bridge_jar  # noqa: F401  (re-exported pytest fixture)

from squall.backends.sqlite import SqliteBackend
from squall.dclgen import generate, write

# The program: CRUD round-trip driven entirely off the GENERATED ACCTREC record.
# NOTE: the procedure-division EXEC SQL blocks are deliberately NOT period-
# terminated, so adjacent statements (INSERT immediately followed by SELECT, etc.)
# exercise the ProLeap adjacency fix (red-dragon-g64e). Before that fix the
# adjacent blocks merged into one statement and the SQL was malformed.
_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CRUDTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL INCLUDE ACCTREC END-EXEC.
       01  WS-BAL        PIC S9(5)V9(2) COMP-3.
       01  WS-BAL2       PIC S9(5)V9(2) COMP-3.
       01  WS-CODE-INS   PIC S9(9) COMP.
       01  WS-CODE-DEL   PIC S9(9) COMP.
       PROCEDURE DIVISION.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           MOVE 11 TO ACCT-ID.
           MOVE 1234.56 TO ACCT-BAL.
           MOVE 'ALICE' TO ACCT-NAME.
           EXEC SQL
               INSERT INTO ACCOUNT (ACCT_ID, ACCT_BAL, ACCT_NAME)
               VALUES (:ACCT-ID, :ACCT-BAL, :ACCT-NAME)
           END-EXEC
           EXEC SQL
               SELECT ACCT_BAL INTO :WS-BAL
               FROM ACCOUNT WHERE ACCT_ID = :ACCT-ID
           END-EXEC
           MOVE SQLCODE TO WS-CODE-INS.
           MOVE 2000.00 TO ACCT-BAL.
           EXEC SQL
               UPDATE ACCOUNT SET ACCT_BAL = :ACCT-BAL
               WHERE ACCT_ID = :ACCT-ID
           END-EXEC
           EXEC SQL
               SELECT ACCT_BAL INTO :WS-BAL2
               FROM ACCOUNT WHERE ACCT_ID = :ACCT-ID
           END-EXEC
           EXEC SQL
               DELETE FROM ACCOUNT WHERE ACCT_ID = :ACCT-ID
           END-EXEC
           EXEC SQL
               SELECT ACCT_BAL INTO :WS-BAL
               FROM ACCOUNT WHERE ACCT_ID = :ACCT-ID
           END-EXEC
           MOVE SQLCODE TO WS-CODE-DEL.
           STOP RUN.
"""


def test_crud_round_trip_on_generated_copybook(bridge_jar, tmp_path):
    # 1. Live schema -> backend connection.
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE ACCOUNT ("
        " ACCT_ID INTEGER NOT NULL,"
        " ACCT_BAL DECIMAL(7,2),"
        " ACCT_NAME CHAR(20))"
    )

    # 2. Run dclgen on the live schema -> generated copybook in a temp dir.
    rec = generate(conn, "ACCOUNT", record_name="ACCTREC")
    assert write(rec, tmp_path) == tmp_path / "ACCTREC.cpy"
    assert not (tmp_path / "ACCTREC.json").exists()

    # 3. Drive the whole pipeline on the GENERATED copybook.
    backend = SqliteBackend(conn)
    vm = run_cobol(
        _PROGRAM,
        bridge_jar,
        connections={"SAMPLE": backend},
        copybook_dirs=[tmp_path],
        max_steps=4000,
    )

    # 4a. INSERT then SELECT round-tripped the packed balance through the real VM.
    assert read_ws_field(vm, "WS-BAL") == Decimal("1234.56")
    assert read_ws_field(vm, "WS-CODE-INS") == 0

    # 4b. UPDATE then SELECT saw the new value.
    assert read_ws_field(vm, "WS-BAL2") == Decimal("2000.00")

    # 4c. DELETE removed the row: the post-delete SELECT reports SQLCODE 100,
    #     and the row is actually gone from the database.
    assert read_ws_field(vm, "WS-CODE-DEL") == 100
    assert (
        conn.execute("SELECT COUNT(*) FROM ACCOUNT WHERE ACCT_ID = 11").fetchone()[0]
        == 0
    )


# A VARCHAR host var is the 49-group; the program sets its LEN/TEXT children, the
# codec binds the length-prefixed value on INSERT, and writes it back on SELECT.
_VARCHAR_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. VCHTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL INCLUDE EMPREC END-EXEC.
       PROCEDURE DIVISION.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           MOVE 10 TO EMP-ID.
           MOVE 7 TO EMP-NAME-LEN.
           MOVE 'SANDERS' TO EMP-NAME-TEXT.
           EXEC SQL
               INSERT INTO EMP (EMP_ID, EMP_NAME)
               VALUES (:EMP-ID, :EMP-NAME)
           END-EXEC
           MOVE SPACES TO EMP-NAME-TEXT.
           MOVE 0 TO EMP-NAME-LEN.
           EXEC SQL
               SELECT EMP_NAME INTO :EMP-NAME
               FROM EMP WHERE EMP_ID = :EMP-ID
           END-EXEC
           STOP RUN.
"""


def test_varchar_round_trip_on_generated_copybook(bridge_jar, tmp_path):
    # Live schema with a VARCHAR column -> generated 49-group copybook.
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE EMP (EMP_ID INTEGER NOT NULL, EMP_NAME VARCHAR(9))")
    rec = generate(conn, "EMP", record_name="EMPREC")
    write(rec, tmp_path)

    # The strategy infers EMP-NAME's VARCHAR shape from the copybook's 49-level
    # LEN/TEXT group; that shape reaches the binding VARCHAR codec.
    backend = SqliteBackend(conn)
    vm = run_cobol(
        _VARCHAR_PROGRAM,
        bridge_jar,
        connections={"SAMPLE": backend},
        copybook_dirs=[tmp_path],
        max_steps=4000,
    )

    # The INSERT bound 'SANDERS' (LEN 7) through the 49-group; the SELECT wrote it
    # back into the (cleared) host var: LEN restored to 7, TEXT to 'SANDERS'.
    assert read_ws_field(vm, "EMP-NAME-LEN") == 7
    assert read_ws_field(vm, "EMP-NAME-TEXT").rstrip() == "SANDERS"
    # And it actually round-tripped through the database.
    assert (
        conn.execute("SELECT EMP_NAME FROM EMP WHERE EMP_ID = 10").fetchone()[0]
        == "SANDERS"
    )
