"""Integration: VSAM browse round-trips real records (Task D3b).

The JAR-gated test drives a COBOL program through the REAL run_cics path with a
``CicsLoweringStrategy`` constructed with a ``vsam_engine`` built from a temp FCT.
The program WRITEs two records, STARTBRs, READNEXTs through them, MOVEs the
second record's body into the COMMAREA, and RETURNs — asserting the browsed
read-back bytes round-trip.
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
from cics.vsam.engine import VsamEngine
from cics.vsam.file_table import cics_files
from tests.covers import covers
from tests.vsam_system import SeedCluster, build_test_system
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


# Record layout: 4-byte key + 6-byte body = 10 bytes. Two records written;
# browse forward returns them in key order, so the 2nd READNEXT yields BB02.
# WS-KEY is LOW-VALUES so STARTBR positions before the first record: in EBCDIC
# the letter keys (0xC1..) sort BELOW digit keys (0xF0..), so a numeric RIDFLD
# like '0000' would sort ABOVE 'AA01' and (correctly) position past end-of-file.
COBOL_BROWSE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTBRWS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-KEY  PIC X(4) VALUE LOW-VALUES.
       01 WS-REC.
          05 WS-REC-KEY  PIC X(4).
          05 WS-REC-BODY PIC X(6).
       01 WS-RD.
          05 WS-RD-KEY  PIC X(4).
          05 WS-RD-BODY PIC X(6).
       01 WS-CA.
          05 WS-CA-BODY PIC X(6).
       PROCEDURE DIVISION.
           MOVE 'AA01' TO WS-REC-KEY.
           MOVE 'ALPHA!' TO WS-REC-BODY.
           EXEC CICS WRITE FILE('TESTDS') FROM(WS-REC)
               RIDFLD(WS-REC-KEY) END-EXEC.
           MOVE 'BB02' TO WS-REC-KEY.
           MOVE 'BRAVO!' TO WS-REC-BODY.
           EXEC CICS WRITE FILE('TESTDS') FROM(WS-REC)
               RIDFLD(WS-REC-KEY) END-EXEC.
           EXEC CICS STARTBR FILE('TESTDS') RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS READNEXT FILE('TESTDS') INTO(WS-RD)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS READNEXT FILE('TESTDS') INTO(WS-RD)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS ENDBR FILE('TESTDS') END-EXEC.
           MOVE WS-RD-BODY TO WS-CA-BODY.
           EXEC CICS RETURN TRANSID('CC01') COMMAREA(WS-CA) END-EXEC.
           STOP RUN.
"""


def _engine(tmp_path: Path) -> VsamEngine:
    clusters = (SeedCluster("TESTDS", 10, 4, ()),)
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


@covers(CobolFeature.EXEC_CICS)
def test_vsam_browse_forward_round_trips(cobol_parser, tmp_path):
    """STARTBR + two READNEXTs walk records in key order; 2nd record body reaches COMMAREA."""
    import queue

    context_holder = [CicsContext(transid="CC00", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        result_holder=result_holder,
        vsam_engine=_engine(tmp_path),
    )
    strategy = CicsLoweringStrategy(
        conversational=False, handler_source=[], unsupported_verbs=set()
    )
    source = apply_cics_prepass(COBOL_BROWSE).encode()
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
    expected = "BRAVO!".encode("cp037")
    assert (
        result.commarea == expected
    ), f"VSAM browse read-back did not round-trip: {result.commarea!r} (expected {expected!r})"
