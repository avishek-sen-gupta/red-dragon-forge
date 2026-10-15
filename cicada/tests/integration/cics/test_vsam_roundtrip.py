"""Integration: VSAM WRITE then READ round-trips a real record (Task D3a).

The JAR-gated test drives a COBOL program through the REAL run_cics path with a
``CicsLoweringStrategy`` constructed with a ``vsam_engine`` built from a temp FCT.
The program WRITEs a record, then READs it back INTO a second field, MOVEs that
field into the COMMAREA, and RETURNs — asserting the read-back bytes round-trip.
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


# Record layout: 4-byte key + 6-byte body = 10 bytes.
COBOL_VSAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTVSAM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-KEY  PIC X(4) VALUE 'AA01'.
       01 WS-REC.
          05 WS-REC-KEY  PIC X(4).
          05 WS-REC-BODY PIC X(6).
       01 WS-REC2.
          05 WS-REC2-KEY  PIC X(4).
          05 WS-REC2-BODY PIC X(6).
       01 WS-CA.
          05 WS-CA-BODY PIC X(6).
       PROCEDURE DIVISION.
           MOVE 'AA01' TO WS-REC-KEY.
           MOVE 'HELLO!' TO WS-REC-BODY.
           EXEC CICS WRITE FILE('TESTDS') FROM(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS READ FILE('TESTDS') INTO(WS-REC2)
               RIDFLD(WS-KEY) END-EXEC.
           MOVE WS-REC2-BODY TO WS-CA-BODY.
           EXEC CICS RETURN TRANSID('CC01') COMMAREA(WS-CA) END-EXEC.
           STOP RUN.
"""


def _engine(tmp_path: Path) -> VsamEngine:
    clusters = (SeedCluster("TESTDS", 10, 4, ()),)
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


@covers(CobolFeature.EXEC_CICS)
def test_vsam_write_then_read_round_trips(cobol_parser, tmp_path):
    """WRITE FROM(WS-REC) then READ INTO(WS-REC2) carries the body to the COMMAREA."""
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
    source = apply_cics_prepass(COBOL_VSAM).encode()
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
    expected = "HELLO!".encode("cp037")
    assert (
        result.commarea == expected
    ), f"VSAM read-back did not round-trip: {result.commarea!r} (expected {expected!r})"


# DATASET(...) synonym for FILE(...), with the dataset name in a DATA-NAME
# (PIC X(8) VALUE 'TESTDS') rather than a literal — the real CardDemo idiom.
COBOL_VSAM_DATASET = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTDSN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DSN  PIC X(8) VALUE 'TESTDS'.
       01 WS-KEY  PIC X(4) VALUE 'AA01'.
       01 WS-REC.
          05 WS-REC-KEY  PIC X(4).
          05 WS-REC-BODY PIC X(6).
       01 WS-REC2.
          05 WS-REC2-KEY  PIC X(4).
          05 WS-REC2-BODY PIC X(6).
       01 WS-CA.
          05 WS-CA-BODY PIC X(6).
       PROCEDURE DIVISION.
           MOVE 'AA01' TO WS-REC-KEY.
           MOVE 'HELLO!' TO WS-REC-BODY.
           EXEC CICS WRITE DATASET(WS-DSN) FROM(WS-REC)
               RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS READ DATASET(WS-DSN) INTO(WS-REC2)
               RIDFLD(WS-KEY) END-EXEC.
           MOVE WS-REC2-BODY TO WS-CA-BODY.
           EXEC CICS RETURN TRANSID('CC01') COMMAREA(WS-CA) END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_vsam_dataset_keyword_and_dataname_resolution(cobol_parser, tmp_path):
    """READ/WRITE DATASET(WS-DSN) resolves the synonym + data-name to its value."""
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
    source = apply_cics_prepass(COBOL_VSAM_DATASET).encode()
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
    expected = "HELLO!".encode("cp037")
    assert result.commarea == expected, (
        f"DATASET(WS-DSN) data-name not resolved: {result.commarea!r} "
        f"(expected {expected!r})"
    )
