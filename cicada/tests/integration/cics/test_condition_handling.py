"""Integration: EXEC CICS condition raising and HANDLE CONDITION dispatch."""

from __future__ import annotations

import queue
import re
import struct
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.conditions import MAX_CODE
from cics.coprocessor import build_cics_spec
from cics.dispatcher import run_cics
from cics.preprocessor import raisable_literal
from cics.types import CicsContext
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature

from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

_CICS_COPYBOOKS = Path(__file__).resolve().parents[3] / "cics" / "copybooks"
_DFHHANDLE_CPY = _CICS_COPYBOOKS / "DFHHANDLE.cpy"


@pytest.fixture(autouse=True)
def _require_bridge_jar(bridge_jar):  # noqa: F811
    """Fails loudly when PROLEAP_BRIDGE_JAR is unset."""


@pytest.fixture
def cobol_parser(bridge_jar):  # noqa: F811
    runner = RealSubprocessRunner()
    return ProLeapCobolParser(runner, bridge_jar, copybook_dirs=[_CICS_COPYBOOKS])


def _copybook_capture(pattern: str) -> str:
    """The single capture of `pattern` in DFHHANDLE.cpy. Raises IndexError when
    the copybook no longer has the shape these tests guard, which is itself the
    drift this file exists to catch."""
    return re.findall(pattern, _DFHHANDLE_CPY.read_text())[0]


def test_the_copybook_literal_matches_the_condition_table():
    """The copybook's Y positions are generated from conditions.py. This reads the
    committed copybook, not a recomputation, so a stale paste cannot pass."""
    assert _copybook_capture(r"'([NY]+)'") == raisable_literal()


def test_the_copybook_table_sizes_match_the_condition_table():
    """One slot per DFHRESP code, and twice the bytes for the handler area because
    S9(4) COMP is two bytes per slot. A code above the largest one the copybook was
    generated for would index out of bounds."""
    slots = MAX_CODE + 1
    assert int(_copybook_capture(r"DFH-RAISABLE-BYTES PIC X\((\d+)\)")) == slots
    assert int(_copybook_capture(r"DFH-RAISABLE OCCURS (\d+) TIMES")) == slots
    assert int(_copybook_capture(r"DFH-HANDLER-BYTES PIC X\((\d+)\)")) == slots * 2
    assert int(_copybook_capture(r"DFH-HANDLER OCCURS (\d+) TIMES")) == slots


COBOL_READS_ITS_OWN_TABLE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDPROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-NOTFND  PIC X.
           05  WS-CA-NORMAL  PIC X.
           05  WS-CA-MAPFAIL PIC X.
       PROCEDURE DIVISION.
           MOVE DFH-RAISABLE(14) TO WS-CA-NOTFND.
           MOVE DFH-RAISABLE(1)  TO WS-CA-NORMAL.
           MOVE DFH-RAISABLE(37) TO WS-CA-MAPFAIL.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_the_injected_table_is_visible_to_the_program(cobol_parser):
    """DFH-RAISABLE(14) is NOTFND (code 13, 1-based) and must be Y; slot 1 is
    NORMAL and must not be; slot 37 is MAPFAIL, the last slot, and must be Y —
    that is the subscript a wrong OCCURS count would run past."""
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
    assert result.commarea[2:3] == "Y".encode("cp037")


COBOL_HANDLE_WRITES_THE_SLOT = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDWRITE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-NOTFND  PIC S9(4) COMP.
           05  WS-CA-ERROR   PIC S9(4) COMP.
           05  WS-CA-LENGERR PIC S9(4) COMP.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) END-EXEC.
           EXEC CICS HANDLE CONDITION ERROR(PARA-B) END-EXEC.
           EXEC CICS HANDLE CONDITION LENGERR(PARA-A) END-EXEC.
           MOVE DFH-HANDLER(14) TO WS-CA-NOTFND.
           MOVE DFH-HANDLER(2)  TO WS-CA-ERROR.
           MOVE DFH-HANDLER(23) TO WS-CA-LENGERR.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-A.
           EXEC CICS RETURN END-EXEC.
       PARA-B.
           EXEC CICS RETURN END-EXEC.
"""


@pytest.mark.xfail(
    reason="handler_labels is empty until Task 5 wires collect_handler_labels "
    "into compilation; the write emits index 0. Remove this marker then.",
    strict=True,
)
@covers(CobolFeature.EXEC_CICS)
def test_handle_condition_writes_the_label_index_into_its_slot(cobol_parser):
    """PARA-A is index 1 and PARA-B index 2, so NOTFND holds 1, ERROR 2, and
    LENGERR 1 again — the same paragraph keeps one index. The three slots hold
    three different pairings, so a write shifted by one slot reads back 0.

    One condition per HANDLE CONDITION: ProLeap's own COBOL grammar rejects a
    second condition in the same statement ("missing END_EXEC at 'EXEC'"), even
    though cicada's EXEC CICS grammar parses it."""
    context_holder = [CicsContext(transid="HND1", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(
        COBOL_HANDLE_WRITES_THE_SLOT.encode(), cobol_parser, spec
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )

    assert result.commarea[0:2] == struct.pack(">h", 1)
    assert result.commarea[2:4] == struct.pack(">h", 2)
    assert result.commarea[4:6] == struct.pack(">h", 1)


COBOL_OVERRIDE_AND_IGNORE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDOVER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-AFTER-OVERRIDE PIC S9(4) COMP.
           05  WS-CA-AFTER-IGNORE   PIC S9(4) COMP.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) END-EXEC.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-B) END-EXEC.
           MOVE DFH-HANDLER(14) TO WS-CA-AFTER-OVERRIDE.
           EXEC CICS IGNORE CONDITION NOTFND END-EXEC.
           MOVE DFH-HANDLER(14) TO WS-CA-AFTER-IGNORE.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-A.
           EXEC CICS RETURN END-EXEC.
       PARA-B.
           EXEC CICS RETURN END-EXEC.
"""


@pytest.mark.xfail(
    reason="handler_labels is empty until Task 5 wires collect_handler_labels "
    "into compilation; the overriding write emits index 0. Remove this marker then.",
    strict=True,
)
@covers(CobolFeature.EXEC_CICS)
def test_a_later_handle_overrides_and_ignore_cancels(cobol_parser):
    """Override and cancellation are just later writes to the same slot."""
    context_holder = [CicsContext(transid="HND2", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(
        COBOL_OVERRIDE_AND_IGNORE.encode(), cobol_parser, spec
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
    )

    assert result.commarea[0:2] == struct.pack(">h", 2)
    assert result.commarea[2:4] == struct.pack(">h", 0)
