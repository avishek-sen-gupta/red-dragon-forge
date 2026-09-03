"""Integration: EXEC CICS condition raising and HANDLE CONDITION dispatch."""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.conditions import MAX_CODE, RAISABLE, code_for
from cics.coprocessor import build_cics_spec
from cics.dispatcher import run_cics
from cics.types import CicsContext
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature

from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar

_CICS_COPYBOOKS = Path(__file__).resolve().parents[3] / "cics" / "copybooks"


@pytest.fixture(autouse=True)
def _require_bridge_jar(bridge_jar):
    """Fails loudly when PROLEAP_BRIDGE_JAR is unset."""


@pytest.fixture
def cobol_parser(bridge_jar):
    runner = RealSubprocessRunner()
    return ProLeapCobolParser(runner, bridge_jar, copybook_dirs=[_CICS_COPYBOOKS])


def test_the_raisable_literal_matches_the_condition_table():
    """The copybook's Y positions are generated from conditions.py; regenerate
    and compare so the two cannot drift."""
    from cics.preprocessor import raisable_literal

    expected = "".join(
        "Y" if code in {code_for(n) for n in RAISABLE} else "N"
        for code in range(MAX_CODE + 1)
    )
    assert raisable_literal() == expected


COBOL_READS_ITS_OWN_TABLE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDPROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-NOTFND  PIC X.
           05  WS-CA-NORMAL  PIC X.
       PROCEDURE DIVISION.
           MOVE DFH-RAISABLE(14) TO WS-CA-NOTFND.
           MOVE DFH-RAISABLE(1)  TO WS-CA-NORMAL.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_the_injected_table_is_visible_to_the_program(cobol_parser):
    """DFH-RAISABLE(14) is NOTFND (code 13, 1-based) and must be Y; slot 1 is
    NORMAL and must not be."""
    context_holder = [CicsContext(transid="HND0", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(
        COBOL_READS_ITS_OWN_TABLE.encode(), cobol_parser, spec
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )

    assert result.commarea[0:1] == "Y".encode("cp037")
    assert result.commarea[1:2] == "N".encode("cp037")
