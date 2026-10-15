"""Integration: EIBRESP / RESP(name) write-back after a CICS service verb.

Task F2 of the CICS field-ref wiring plan.

A program does ``EXEC CICS INQUIRE PROGRAM(WS-MISSING) RESP(WS-RC)`` for a
program that is NOT in the program cache, so the INQUIRE builtin returns 27
(PGMIDERR). The write-back must store 27 into WS-RC; the program then checks
``IF WS-RC = DFHRESP(PGMIDERR)`` and sets a flag MOVEd into the COMMAREA. The
test asserts the flag round-trips, proving the resp code was written into the
RESP field and decoded correctly from a COMP binary field.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interpreter.project.cobol_compile import compile_cobol
from cics.statements import CicsDialectParser
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature
from cics.preprocessor import apply_cics_prepass
from cics.strategy import CicsLoweringStrategy
from cics.runtime import install_cics_runtime
from cics.types import CicsContext, DispatchKind
from cics.dispatcher import run_cics
from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"


@pytest.fixture(autouse=True)
def _require_bridge_jar(bridge_jar):
    """Enforce the required PROLEAP_BRIDGE_JAR for run()/compile_directory-based
    tests (fails loudly via bridge_jar if it's unset)."""


@pytest.fixture
def cobol_parser(bridge_jar):
    runner = RealSubprocessRunner()
    return ProLeapCobolParser(runner, bridge_jar, copybook_dirs=[_CICS_COPYBOOKS])


COBOL_RESP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTRESP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MISSING PIC X(8) VALUE 'NOPROG  '.
       01 WS-RC      PIC S9(8) COMP.
       01 WS-CA.
          05 WS-CA-FLAG PIC X(1).
       PROCEDURE DIVISION.
           MOVE 'N' TO WS-CA-FLAG.
           EXEC CICS INQUIRE PROGRAM(WS-MISSING) RESP(WS-RC)
               NOHANDLE END-EXEC.
           IF WS-RC = DFHRESP(PGMIDERR)
               MOVE 'Y' TO WS-CA-FLAG
           END-IF.
           EXEC CICS RETURN TRANSID('CC01') COMMAREA(WS-CA) END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_inquire_resp_writeback_round_trips(cobol_parser):
    """INQUIRE of a missing program writes PGMIDERR(27) to WS-RC; IF check fires."""
    import queue

    context_holder = [CicsContext(transid="CC00", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        result_holder=result_holder,
    )
    strategy = CicsLoweringStrategy(
        conversational=False, handler_source=[], unsupported_verbs=set()
    )
    source = apply_cics_prepass(COBOL_RESP).encode()
    program = compile_cobol(
        source,
        parser=cobol_parser,
        extension_strategies=[strategy],
        dialect_parsers=[CicsDialectParser()],
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )

    assert result.kind == DispatchKind.RETURN_TRANSID
    # The IF WS-RC = DFHRESP(PGMIDERR) check fired, setting the flag to 'Y'.
    expected = "Y".encode("cp037")
    assert result.commarea == expected, (
        f"RESP(WS-RC) write-back did not round-trip: flag={result.commarea!r} "
        f"(expected {expected!r}); WS-RC likely was not set to PGMIDERR"
    )
