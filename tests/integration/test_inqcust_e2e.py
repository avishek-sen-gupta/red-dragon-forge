"""Integration: real Bank-of-Z INQCUST runs end-to-end via CICS+SQL composition.

INQCUST is invoked via EXEC CICS LINK in real CICS (never as a top-level
transaction entry), so this test follows the precedent found during planning
(cicada's own tests/integration/cics/test_link.py::test_link_commarea_written_back):
a small synthetic WRAPPER driver program LINKs to the real INQCUST, then does
RETURN TRANSID(...) COMMAREA(...) so the test can observe the result via
DispatchResult.commarea -- run_cics on a bare top-level RETURN does not expose
the mutated COMMAREA.

Two empirical corrections vs. the plan's first-draft test (both confirmed by
direct investigation against the real compiled program, not assumed):

1. WRAPPER must itself receive the incoming top-level COMMAREA through its own
   LINKAGE SECTION (``PROCEDURE DIVISION USING DFHCOMMAREA``) and copy it into
   its WORKING-STORAGE WS-CA before LINKing. A top-level CICS transaction's
   COMMAREA is only wired into a program's own DFHCOMMAREA (LINKAGE SECTION) --
   never automatically into an arbitrary WORKING-STORAGE record. Without this,
   WS-CA always starts at its WORKING-STORAGE-initial (zeroed) value regardless
   of what CicsContext.commarea carries, so every seeded input (sort code,
   customer number) is silently lost before WRAPPER even calls LINK.

2. The COMMAREA bytes RedDragon's VM operates on are EBCDIC (cp037), not
   ASCII/UTF-8 -- confirmed by cicada's own test_link.py, which decodes its
   result commarea via .decode("cp037"). Seeding and reading back COMMAREA
   bytes must go through cp037, not plain str.encode()/bytes literals.

The ``INQCUST-INQ-SUCCESS`` field's offset is read from WRAPPER's OWN field
layout (not INQCUST's) because it is a LINKAGE SECTION field of INQCUST's
DFHCOMMAREA, which never gets a layout entry for the compiled INQCUST program
at all. WRAPPER copies INQCUSTZ into its own WORKING-STORAGE WS-CA record, and
WORKING-STORAGE fields DO get layout entries, so WRAPPER's own layout is the
correct (and only working) place to resolve the field's offset -- exactly the
buffer DispatchResult.commarea returns.  The offset is relative to WS-CA's own
start (field offset minus WS-CA's own offset), since the returned COMMAREA
buffer IS the WS-CA bytes, not the full WORKING-STORAGE region.

This test also required two real upstream fixes, made during this task's
investigation (not workarounds in this file):
- cicada's CICS grammar rejected FORMATTIME's bare DATESEP (no operand) --
  real CICS syntax is DATESEP[(separator)], optional; INQCUST's own
  (unreachable, in this test's found/not-found paths) error-handling section
  uses the bare form, and the WHOLE program must compile regardless of which
  branches actually execute.
- squall's EXEC SQL CONNECT model required an explicit CONNECT before any SQL
  data statement; a real CICS-Db2-attached program like INQCUST never issues
  one itself (the CICS Db2 attachment facility hands it an already-connected
  thread). squall now accepts an ``initial_connector`` (a ``DbConnector``) to
  model that.
"""

from __future__ import annotations

import os
import queue
from pathlib import Path

import ibm_db
import pytest

from cics.dispatcher import run_cics
from cobol_harness.compile import main_entry
from cics.types import CicsContext, DispatchKind

from squall.backends.db2 import Db2Backend
from squall.connector import NamedDbConnector

from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.transaction_hooks import TransactionHooks
from squall.coprocessor import build_sql_spec
from squall.runtime import install_sql_runtime
from interpreter.cobol.layout_data import field_positions
from interpreter.project.coprocessor_compile import compile_program
from interpreter.run import declarations_of
from tests.integration.forge_cobol_helpers import make_parser

_BANK_OF_Z_COPY = (
    Path(__file__).parents[2]
    / "vendor"
    / "bank-of-z"
    / "src"
    / "base"
    / "cics"
    / "copy"
)
_BANK_OF_Z_COBOL = (
    Path(__file__).parents[2]
    / "vendor"
    / "bank-of-z"
    / "src"
    / "base"
    / "cics"
    / "cobol"
)

# INQCUSTZ.cpy field widths (see this module's docstring / INQCUSTZ.cpy).
_EYE_LEN = 4
_SCODE_LEN = 6
_CUSTNO_LEN = 10

_SORT_CODE = "123456"
_FOUND_CUSTNO = "0000000001"
# Deliberately NOT all-9s (9999999999): that value triggers INQCUST's
# "last customer in use" lookup via a named-counter-server path this test does
# not exercise. 0000009999 is just an ordinary, absent customer number.
_NOT_FOUND_CUSTNO = "0000009999"

# WRAPPER receives the top-level COMMAREA through its own LINKAGE SECTION (a
# real top-level CICS transaction only wires COMMAREA into a program's own
# DFHCOMMAREA -- never into an arbitrary WORKING-STORAGE record), copies it
# into WORKING-STORAGE WS-CA, LINKs to the real INQCUST with WS-CA, then hands
# the (possibly mutated) WS-CA back via RETURN TRANSID so the test can observe
# it -- mirrors cicada's own test_link.py::test_link_commarea_written_back.
_WRAPPER_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WRAPPER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CA.
           COPY INQCUSTZ.
       LINKAGE SECTION.
       01 DFHCOMMAREA.
           COPY INQCUSTZ.
       PROCEDURE DIVISION USING DFHCOMMAREA.
       MAIN-PARA.
           MOVE DFHCOMMAREA TO WS-CA.
           EXEC CICS LINK PROGRAM('INQCUST')
                     COMMAREA(WS-CA)
                     LENGTH(LENGTH OF WS-CA)
           END-EXEC.
           EXEC CICS RETURN TRANSID('WRAP') COMMAREA(WS-CA)
           END-EXEC.
"""


def _seed_commarea(sort_code: str, custno: str, total_len: int) -> bytes:
    """Build a DFHCOMMAREA/INQCUSTZ-shaped COMMAREA in EBCDIC (cp037) -- the
    encoding RedDragon's VM operates on for COBOL data (confirmed via cicada's
    own test_link.py, which reads back COMMAREA bytes via .decode("cp037"))."""
    eye = " " * _EYE_LEN
    scode = sort_code.ljust(_SCODE_LEN)[:_SCODE_LEN]
    cust = custno.rjust(_CUSTNO_LEN, "0")[:_CUSTNO_LEN]
    body = (eye + scode + cust).encode("cp037")
    # The remainder of the commarea (output fields) starts zeroed; INQCUST
    # overwrites what it needs and WRAPPER hands the whole buffer back.
    return body + b"\x00" * (total_len - len(body))


def _seed_customer(conn) -> None:
    """Create CUSTOMER (matching Bank-of-Z's CUSTDB2.cpy DECLARE TABLE) and
    insert the found-case row. MOJO has no CUSTOMER table by default --
    verified empirically (SYSCAT.TABLES has no CUSTOMER row before this runs,
    and squall's own Db2 tests only ever created ACCOUNT/ROUTED) -- so this
    test owns the table's lifecycle end-to-end, create through drop, mirroring
    test_db2_connect_e2e.py's create/drop-per-test pattern."""
    try:
        ibm_db.exec_immediate(conn, "DROP TABLE CUSTOMER")
    except Exception:  # noqa: BLE001 -- table may not exist yet
        pass
    ibm_db.exec_immediate(
        conn,
        """
        CREATE TABLE CUSTOMER (
          CUSTOMER_EYECATCHER     CHAR(4),
          CUSTOMER_SORTCODE       CHAR(6) NOT NULL,
          CUSTOMER_NUMBER         CHAR(10) NOT NULL,
          CUSTOMER_TITLE          CHAR(10),
          CUSTOMER_FIRST_NAME     CHAR(50),
          CUSTOMER_LAST_NAME      CHAR(50),
          CUSTOMER_DATE_OF_BIRTH  INTEGER,
          CUSTOMER_PHONE          CHAR(20),
          CUSTOMER_ADDR_LINE1     CHAR(50),
          CUSTOMER_ADDR_LINE2     CHAR(50),
          CUSTOMER_CITY           CHAR(50),
          CUSTOMER_POSTCODE       CHAR(10),
          CUSTOMER_COUNTRY        CHAR(50),
          CUSTOMER_STATUS         CHAR(10),
          CUSTOMER_CREATED_DATE   INTEGER,
          CUSTOMER_CREDIT_SCORE   SMALLINT,
          CUSTOMER_CS_REVIEW_DATE INTEGER
        )
        """,
    )
    ibm_db.commit(conn)
    ibm_db.exec_immediate(
        conn,
        "INSERT INTO CUSTOMER (CUSTOMER_EYECATCHER, CUSTOMER_SORTCODE, "
        "CUSTOMER_NUMBER, CUSTOMER_TITLE, CUSTOMER_FIRST_NAME, CUSTOMER_LAST_NAME, "
        "CUSTOMER_DATE_OF_BIRTH, CUSTOMER_PHONE, CUSTOMER_ADDR_LINE1, "
        "CUSTOMER_ADDR_LINE2, CUSTOMER_CITY, CUSTOMER_POSTCODE, CUSTOMER_COUNTRY, "
        "CUSTOMER_STATUS, CUSTOMER_CREATED_DATE, CUSTOMER_CREDIT_SCORE, "
        "CUSTOMER_CS_REVIEW_DATE) VALUES ("
        f"'CUST', '{_SORT_CODE}', '{_FOUND_CUSTNO}', 'MR', 'TESTFIRST', "
        "'TESTLAST', 19800101, '01234567890', 'LINE1', 'LINE2', 'CITY', 'PC1', "
        "'COUNTRY', 'ACTIVE', 20200101, 750, 20210101)",
    )
    ibm_db.commit(conn)


def _drop_customer(conn) -> None:
    try:
        ibm_db.exec_immediate(conn, "DROP TABLE CUSTOMER")
        ibm_db.commit(conn)
    except Exception:  # noqa: BLE001
        pass


def test_inqcust_found_and_not_found(bridge_jar):
    dsn = os.environ["SQUALL_DB2_DSN"]
    conn = ibm_db.connect(dsn, "", "")
    try:
        _seed_customer(conn)

        backend = Db2Backend(conn)
        context_holder: list = [None]
        result_holder: list = [None]
        program_cache: dict = {}

        parser = make_parser(bridge_jar, copybook_dirs=[_BANK_OF_Z_COPY])

        # Compile INQCUST (CICS + SQL) and register it in the shared
        # program_cache so WRAPPER's EXEC CICS LINK can find it by name at run
        # time. NamedDbConnector("SAMPLE") models the CICS Db2 attachment
        # facility: INQCUST never issues EXEC SQL CONNECT itself.
        inqcust_cics_spec = build_cics_spec()
        inqcust_sql_spec = build_sql_spec()
        inqcust_source = (_BANK_OF_Z_COBOL / "INQCUST.cbl").read_bytes()
        inqcust_linked = compile_program(
            inqcust_source, parser, [inqcust_cics_spec, inqcust_sql_spec]
        )
        program_cache["INQCUST"] = inqcust_linked
        sql = install_sql_runtime({"SAMPLE": backend}, NamedDbConnector("SAMPLE"))

        # Compile WRAPPER (CICS only -- it never touches SQL) sharing the SAME
        # context_holder/result_holder/program_cache. The region's table
        # composes squall's entries and hooks in.
        runtime = install_cics_runtime(
            context_holder,
            transid_to_program={},
            result_holder=result_holder,
            program_cache=program_cache,
            hooks=TransactionHooks(sql.reset_session, sql.syncpoint, sql.rollback),
            other_builtins=sql.entries,
        )
        wrapper_spec = build_cics_spec()
        wrapper_parser = make_parser(bridge_jar, copybook_dirs=[_BANK_OF_Z_COPY])
        wrapper_linked = compile_program(
            _WRAPPER_PROGRAM.encode("utf-8"), wrapper_parser, [wrapper_spec]
        )

        # INQCUST-INQ-SUCCESS is a LINKAGE SECTION field of INQCUST's own
        # DFHCOMMAREA and never gets a layout entry for the compiled INQCUST
        # program. WRAPPER's own WORKING-STORAGE WS-CA copies the same
        # INQCUSTZ shape, so its layout is the one that actually carries
        # this field -- and it's the same buffer DispatchResult.commarea
        # returns. The offset is relative to WS-CA's own start.
        wrapper_fields = field_positions(declarations_of(wrapper_linked, "WRAPPER"))
        success_field = wrapper_fields["INQCUST-INQ-SUCCESS"]
        ws_ca_field = wrapper_fields["WS-CA"]
        off = success_field.offset - ws_ca_field.offset
        length = success_field.length
        total_len = ws_ca_field.length

        screen_q: queue.Queue = queue.Queue()
        input_q: queue.Queue = queue.Queue()

        # --- Found case ---
        found_commarea = _seed_commarea(_SORT_CODE, _FOUND_CUSTNO, total_len)
        found_result = run_cics(
            wrapper_linked,
            CicsContext(transid="WRAP", commarea=found_commarea, eibaid="\x7d"),
            screen_q,
            input_q,
            entry=main_entry(wrapper_linked),
            context_holder=context_holder,
            result_holder=result_holder,
            max_steps=50_000,
            builtins=runtime.builtins,
        )
        assert found_result.kind == DispatchKind.RETURN_TRANSID
        assert found_result.commarea is not None
        assert (
            found_commarea[off : off + length].decode("cp037") != "Y"
        ), "sanity: seeded commarea must NOT already contain 'Y' before the run"
        assert found_result.commarea[off : off + length].decode("cp037") == "Y", (
            f"expected INQCUST-INQ-SUCCESS='Y' for a known customer, got "
            f"{found_result.commarea[off:off+length]!r}"
        )

        # --- Not-found case ---
        not_found_commarea = _seed_commarea(_SORT_CODE, _NOT_FOUND_CUSTNO, total_len)
        not_found_result = run_cics(
            wrapper_linked,
            CicsContext(transid="WRAP", commarea=not_found_commarea, eibaid="\x7d"),
            screen_q,
            input_q,
            entry=main_entry(wrapper_linked),
            context_holder=context_holder,
            result_holder=result_holder,
            max_steps=50_000,
            builtins=runtime.builtins,
        )
        assert not_found_result.kind == DispatchKind.RETURN_TRANSID
        assert not_found_result.commarea is not None
        assert not_found_result.commarea[off : off + length].decode("cp037") == "N", (
            f"expected INQCUST-INQ-SUCCESS='N' for an unknown customer, got "
            f"{not_found_result.commarea[off:off+length]!r}"
        )
    finally:
        _drop_customer(conn)
        ibm_db.close(conn)
