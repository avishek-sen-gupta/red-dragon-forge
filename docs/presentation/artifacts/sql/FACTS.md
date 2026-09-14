# SQL section — facts (captured 2026-09-14)

Regenerate: `export PROLEAP_BRIDGE_JAR=vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar; SQUALL_DIR=squall . squall/db2/dsn-env.sh; uv run --no-sync python docs/presentation/capture/db2_inqcust_capture.py`

## What ran, against what
- **Backend:** Docker `squall-db2` (icr.io/db2_community/db2 11.5.9.0), server reports `DB2/LINUXX8664 11.05.0900`, database MOJO, host port 15000 (`squall/.env`, `squall/db2/dsn-env.sh`). Driver `ibm_db` via `squall/squall/backends/db2.py`.
- **Db2 was down when this started:** the container showed "unhealthy" and `db2 connect` returned `SQL1032N No start database manager command was issued`. That matches the failure described in `docs/db2-container-memory.md`. `cd squall && make db2-restart` fixed it; no volume or data was touched. `dmesg` inside the container showed no OOM lines, so the memory-kill cause is **not confirmed**.
- **INQCUST** (`vendor/bank-of-z/src/base/cics/cobol/INQCUST.cbl`, unmodified IBM source) is compiled with the CICS and SQL CoprocessorSpecs. A synthetic WRAPPER calls it with `EXEC CICS LINK` and hands the COMMAREA back via `RETURN TRANSID`. It runs on RedDragon's VM against live Db2 (`tests/integration/test_inqcust_e2e.py`; artifact `inqcust-run.txt`).
  - Found case: 1 SELECT sent to Db2 with 2 bound parameters, returning 1 row of 17 columns. Every INQCUSTZ output field is populated in the returned COMMAREA (403 bytes, cp037), with INQ-SUCCESS=`Y`. Integer DOB 19800101 comes back as DD/MM/YYYY = 01/01/1980, converted by INQCUST's own code.
  - Not-found case: SQLCODE 100 flows back into the program, which sets INQ-SUCCESS=`N` and FAIL-CD=`1`.
  - Timings on this machine (emulated amd64 Db2 on Apple Silicon): compile of INQCUST + WRAPPER 3.45s; run 0.11s found, 0.09s not-found.
  - Two COMMITs per task are recorded, one at INQCUST's RETURN and one at WRAPPER's RETURN. Both come from squall's `__cics_task_end_hook` (`squall/squall/strategy.py`, `_reset_session` in `squall/squall/builtins/exec_sql.py`).
  - Setup that INQCUST does not do itself: the test fixture creates and seeds the CUSTOMER table (`_seed_customer`). `NamedDbConnector("SAMPLE")` stands in for the CICS Db2 attachment facility, because INQCUST never issues CONNECT (`squall/squall/connector.py`).
  - Only INQCUST's `READ-CUSTOMER-DB2` SELECT (line 310) ran. The `GET-LAST-CUSTOMER-DB2` SELECT with `ORDER BY … FETCH FIRST 1 ROW ONLY` (line 675) was **not exercised**; the test avoids customer number 9999999999 on purpose.
  - `DECLARE CUSTOMER TABLE` (`CUSTDB2.cpy`) lives in WORKING-STORAGE and never reached Db2.
- **CICS+SQL in one program** (`tests/integration/test_cics_sql_composition.py`): the test runs on **SQLite**. The capture reran both programs, verbatim, on SQLite and on Db2 with identical recorded SQL (`composition-run.txt`):
  - COMBINED: `SELECT ACCT_BAL … WHERE ACCT_ID = ?` with [42] returns 777, then `EXEC CICS ASSIGN APPLID` and `RETURN`.
  - CURSORPGM: OPEN, then FETCH returns SANDERS. At `EXEC CICS RETURN` the task-end hook issues COMMIT and CLOSE C1, leaving no open cursors.
  - Neither package imports the other; the hook is wired by name only (`squall/squall/strategy.py`).
- **Squall standalone** (no CICS): the unmodified IBM db2-samples `squall/testbed/db2-samples/cobol_mf/cursor.sqb` runs on Db2 (`squall/tests/integration/test_db2_cursor_e2e.py`; `cursor-sqb-run.txt`). OPEN, then FETCH, FETCH, FETCH (SQLCODE 100), then CLOSE. Output shows the two managers; the Clerk row is filtered out. DISPLAY output has literal quote characters around text, a RedDragon DISPLAY formatting quirk that is visible in the capture.

## Executes end-to-end (cited test)
- **SELECT … INTO**, with host-variable input bound as `?` and INTO outputs written back. Db2: `test_inqcust_e2e.py`. SQLite: `squall/tests/integration/test_select_into_e2e.py`.
- **Cursors** (DECLARE, OPEN, FETCH loop, CLOSE). Db2: `test_db2_cursor_e2e.py`. SQLite + CICS: `test_cics_sql_composition.py`.
- **INSERT/UPDATE/DELETE** round trip on a DCLGEN-generated copybook, on SQLite only (`squall/tests/integration/test_crud_e2e.py`).
- **COMMIT/ROLLBACK:** IBM `updat.sqb` rolls back an UPDATE, DELETE and INSERT on Db2 (`test_db2_transactions.py`). Autocommit is switched off in `Db2Backend.__init__`.
- **CONNECT TO / CONNECT RESET**, routing across two Db2 databases (MOJO, MOJO2). A statement with no connection gets -1024; an unknown database name gets -1013 (`test_db2_connect_e2e.py`; handlers in `builtins/exec_sql.py`). SET CONNECTION (-1338) and DISCONNECT have handlers, but no e2e test was found for them.
- **WHENEVER SQLERROR GO TO:** a SELECT from a missing table gets -204 from Db2 and branches to the handler (`test_db2_whenever_e2e.py`). WHENEVER is a compile-time directive; the lowering adds an `IF SQLCODE <0 / =100 GO TO` after each later statement (`strategy.py`, `_emit_whenever_checks`).
- **INCLUDE SQLCA / INCLUDE <dclgen>:** rewritten to `COPY` before parsing (`squall/squall/preprocess.py`). The bundled `squall/squall/copybooks/SQLCA.cpy` defines SQLCODE as binary `PIC S9(9) COMP`; the COMP-3 path is exercised end-to-end in `test_include_dclgen_e2e.py` (SQLite).
- **Unmodified IBM `static.sqb`** (BEGIN/END DECLARE SECTION, CONNECT … USER/USING, CONNECT RESET, SELECT INTO), on SQLite (`test_db2_static_e2e.py`).

## SQLCODE / SQLCA handling
- Only **SQLCODE** is written, as 0, 100, or the real negative Db2 code parsed from `ibm_db.get_sqlcode()` (`binding.py` `write_sqlcode`; `backends/db2.py` `_last_sqlcode`). SQLSTATE, SQLERRM, SQLERRD (including row counts) and SQLWARN are declared in SQLCA.cpy but **never populated**.
- Host-variable assignment is strict. A cross-family value gets -301, overflow or truncation gets -304, NULL gets -305, and nothing is written (`binding.py`, coercion layer). Real DB2 would convert-with-warning in some of these cases; that work is deferred as squall-ud0.

## Parses only (grammar `squall/squall/parser/grammar.lark`; `squall/tests/unit/test_grammar_matrix.py`)
- **Dynamic SQL and friends:** PREPARE, EXECUTE / EXECUTE IMMEDIATE, DESCRIBE, CALL, ALLOCATE CURSOR, ASSOCIATE, GET DIAGNOSTICS, SIGNAL, locators, MERGE, VALUES INTO, SAVEPOINT/RELEASE, LOCK, SET. None of these has a handler. They fall through to `_h_query` and their text is sent to the backend verbatim, which is untested (`builtins/exec_sql.py`, `_HANDLERS`). The design doc lists dynamic SQL and CALL as deferred (`squall/docs/design/2026-06-13-exec-sql-support-design.md` §13).
- **WHENEVER SQLWARNING** and custom conditions parse but never branch (`strategy.py`, `_WHENEVER_RELATION`).
- **Indicator variables** `:HV:IND` are split correctly by the parser (`squall/squall/parse.py`), but binding receives only the host-variable names. The indicator is never read or set, so NULL always gives -305 (`builtins/exec_sql.py`, `_host_names`; design doc §11 deferrals).
- **WHERE CURRENT OF** parses (`cur_of` rule), but no runtime test was found.

## DCLGEN
- `squall/squall/dclgen.py` `generate()` reads the schema through **SQLite `PRAGMA table_info` only** (no Db2 catalog reader). It emits a COBOL record plus a JSON sidecar. Supported types: INTEGER/SMALLINT/BIGINT as binary COMP, DECIMAL/NUMERIC as COMP-3, CHAR as PIC X, VARCHAR as a 49-level group. Floating point, TEXT and BLOB raise NotImplementedError.
- The module docstring still says VARCHAR raises; that is stale, since the code maps it. VARCHAR round trip is tested on SQLite (`test_crud_e2e.py::test_varchar_round_trip_on_generated_copybook`) and at unit level (`squall/tests/unit/test_varchar.py`).
- Bank-of-Z uses **hand-written** host variables (INQCUST `HOST-CUSTOMER-ROW`), not squall DCLGEN output.

## Honest gaps
- INQCUST is the only CICS+Db2 program proven, and only through its primary SELECT path. The other Bank-of-Z Db2 programs were not run here.
- There is no real CICS-Db2 SYNCPOINT coordination. Task end simply commits and closes cursors (`_reset_session`; design §13).
- No dialect translation: SQL text goes to the backend unchanged. SQLite-only tests do not prove the same SQL works on Db2.
- The Db2 container is memory-fragile under emulation (`docs/db2-container-memory.md`, bead forge-zka). It needed a restart before this capture.
