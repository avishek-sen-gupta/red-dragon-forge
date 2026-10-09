# tests/integration/test_cics_adapter.py
from __future__ import annotations

import queue
from pathlib import Path

import cics
from cics.dispatcher import run_cics
from cics.types import CicsContext, DispatchKind

from cics.coprocessor import build_cics_spec
from interpreter.project.coprocessor_compile import compile_program

# The prepass injects `COPY DFHEIBLK.` into WORKING-STORAGE; ProLeap resolves
# that copybook against this directory, same as every Cicada CICS integration
# test (see e.g. cicada/tests/integration/cics/test_link.py).
_CICS_COPYBOOKS = Path(cics.__file__).parent / "copybooks"

_CICS_ONLY_PROGRAM = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSONLY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FIELD PIC X(10).
       PROCEDURE DIVISION.
           MOVE 'HELLO' TO WS-FIELD.
           EXEC CICS RETURN
           END-EXEC.
"""

# CALLs the IBM Language Environment service CEEDAYS, which has no CardDemo
# application source (real z/OS supplies it at runtime) -- Cicada ships a
# stub at cics/stubs/CEEDAYS.cbl. Proves the CICS CoprocessorSpec's
# source_search_dirs contribution (cics.le_stubs.LE_STUBS_DIR) resolves
# the CALL without this test doing anything beyond building the spec --
# without that wiring, compile_program would raise on the unresolved CALL.
_CICS_CEEDAYS_PROGRAM = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSCEED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DATE-VS.
          05 WS-DATE-LEN   PIC S9(4) BINARY VALUE 10.
          05 WS-DATE-TXT   PIC X(256) VALUE '2024-01-15'.
       01 WS-FMT-VS.
          05 WS-FMT-LEN    PIC S9(4) BINARY VALUE 10.
          05 WS-FMT-TXT    PIC X(256) VALUE 'YYYY-MM-DD'.
       01 WS-LILIAN        PIC S9(9) BINARY VALUE 0.
       01 WS-FEEDBACK.
          05 WS-FB-SEV     PIC S9(4) BINARY VALUE 0.
          05 WS-FB-MSG     PIC S9(4) BINARY VALUE 0.
          05 FILLER        PIC X(8).
       PROCEDURE DIVISION.
           CALL 'CEEDAYS' USING WS-DATE-VS WS-FMT-VS
                                WS-LILIAN WS-FEEDBACK.
           EXEC CICS RETURN
           END-EXEC.
"""


def test_cics_only_spec_compiles_and_returns(bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    context_holder = [None]
    result_holder = [None]
    spec = build_cics_spec(
        program_cache={}, context_holder=context_holder, result_holder=result_holder
    )
    parser = ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[_CICS_COPYBOOKS]
    )

    _frontend, linked = compile_program(_CICS_ONLY_PROGRAM, parser, [spec])

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    result = run_cics(
        linked,
        CicsContext(transid="CICO", commarea=b"", eibaid="\x7d"),
        screen_q,
        input_q,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=10_000,
    )

    assert result.kind == DispatchKind.RETURN


def test_cics_program_calling_le_service_stub_resolves(bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    context_holder = [None]
    result_holder = [None]
    spec = build_cics_spec(
        program_cache={}, context_holder=context_holder, result_holder=result_holder
    )
    parser = ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[_CICS_COPYBOOKS]
    )

    _frontend, linked = compile_program(_CICS_CEEDAYS_PROGRAM, parser, [spec])

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    result = run_cics(
        linked,
        CicsContext(transid="CICD", commarea=b"", eibaid="\x7d"),
        screen_q,
        input_q,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=10_000,
    )

    assert result.kind == DispatchKind.RETURN
