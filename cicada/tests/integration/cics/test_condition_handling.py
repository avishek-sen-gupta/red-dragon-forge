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


@covers(CobolFeature.EXEC_CICS)
def test_handle_condition_writes_the_label_index_into_its_slot(cobol_parser):
    """PARA-A is index 1 and PARA-B index 2, so NOTFND holds 1, ERROR 2, and
    LENGERR 1 again — the same paragraph keeps one index. The three slots hold
    three different pairings, so a write shifted by one slot reads back 0."""
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


COBOL_MULTI_CONDITION_HANDLE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDMULTI.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-NOTFND  PIC S9(4) COMP.
           05  WS-CA-ERROR   PIC S9(4) COMP.
           05  WS-CA-LENGERR PIC S9(4) COMP.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A)
               ERROR(PARA-B) END-EXEC.
           MOVE DFH-HANDLER(14) TO WS-CA-NOTFND.
           MOVE DFH-HANDLER(2)  TO WS-CA-ERROR.
           MOVE DFH-HANDLER(23) TO WS-CA-LENGERR.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-A.
           EXEC CICS RETURN END-EXEC.
       PARA-B.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_one_statement_naming_several_conditions_writes_each_slot(cobol_parser):
    """A single HANDLE CONDITION naming two conditions is the untested path:
    Task 4's fixture split multi-condition HANDLE into separate statements to
    dodge a ProLeap bug that turned out not to exist. NOTFND(PARA-A) and
    ERROR(PARA-B) are one statement's two conditions, so each must land in its
    own slot with its own paragraph's index; LENGERR is never named here and
    its neighbouring slot must stay 0."""
    context_holder = [CicsContext(transid="HND4", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(
        COBOL_MULTI_CONDITION_HANDLE.encode(), cobol_parser, spec
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
    assert result.commarea[4:6] == struct.pack(">h", 0)


COBOL_OVERRIDE_AND_IGNORE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDOVER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-HANDLER-1 PIC S9(4) COMP.
           05  WS-CA-RAISE-1   PIC X.
           05  WS-CA-HANDLER-2 PIC S9(4) COMP.
           05  WS-CA-RAISE-2   PIC X.
           05  WS-CA-HANDLER-3 PIC S9(4) COMP.
           05  WS-CA-RAISE-3   PIC X.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) END-EXEC.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-B) END-EXEC.
           MOVE DFH-HANDLER(14)  TO WS-CA-HANDLER-1.
           MOVE DFH-RAISABLE(14) TO WS-CA-RAISE-1.
           EXEC CICS IGNORE CONDITION NOTFND END-EXEC.
           MOVE DFH-HANDLER(14)  TO WS-CA-HANDLER-2.
           MOVE DFH-RAISABLE(14) TO WS-CA-RAISE-2.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) END-EXEC.
           MOVE DFH-HANDLER(14)  TO WS-CA-HANDLER-3.
           MOVE DFH-RAISABLE(14) TO WS-CA-RAISE-3.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-A.
           EXEC CICS RETURN END-EXEC.
       PARA-B.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_later_handle_overrides_and_ignore_cancels(cobol_parser):
    """The three CICS states for one condition, in sequence: PARA-B registered
    (index 2, raisable); IGNORE, which must not collapse into "never registered"
    — the handler goes to 0 but the raisable flag goes to 'N', so nothing is
    raised at all; then PARA-A registered again (index 1, raisable restored)."""
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
    assert result.commarea[2:3] == "Y".encode("cp037")
    assert result.commarea[3:5] == struct.pack(">h", 0)
    assert result.commarea[5:6] == "N".encode("cp037")
    assert result.commarea[6:8] == struct.pack(">h", 1)
    assert result.commarea[8:9] == "Y".encode("cp037")


COBOL_RAISABLE_FLAG = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDFLAG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-AFTER-HANDLE PIC X.
           05  WS-CA-AFTER-IGNORE PIC X.
           05  WS-CA-AFTER-AGAIN  PIC X.
           05  WS-CA-PGMIDERR     PIC X.
           05  WS-CA-NEIGHBOUR    PIC X.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) END-EXEC.
           MOVE DFH-RAISABLE(14) TO WS-CA-AFTER-HANDLE.
           EXEC CICS IGNORE CONDITION NOTFND END-EXEC.
           MOVE DFH-RAISABLE(14) TO WS-CA-AFTER-IGNORE.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) END-EXEC.
           MOVE DFH-RAISABLE(14) TO WS-CA-AFTER-AGAIN.
           EXEC CICS HANDLE CONDITION PGMIDERR(PARA-A) END-EXEC.
           MOVE DFH-RAISABLE(28) TO WS-CA-PGMIDERR.
           MOVE DFH-RAISABLE(23) TO WS-CA-NEIGHBOUR.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-A.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_ignore_clears_the_raisable_flag_and_handle_restores_it(cobol_parser):
    """The raisable flag is what separates "ignored" from "never registered", and
    it does not depend on the label map, so this holds before Task 5.

    PGMIDERR is the discriminating case: it is a real condition with a DFHRESP
    code but is not in RAISABLE, so HANDLE must leave its flag 'N' rather than
    silently widening what this runtime raises. LENGERR's slot is read untouched
    to show the subscripted writes land on one slot and do not smear."""
    context_holder = [CicsContext(transid="HND3", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(COBOL_RAISABLE_FLAG.encode(), cobol_parser, spec)

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
    assert result.commarea[3:4] == "N".encode("cp037")
    assert result.commarea[4:5] == "Y".encode("cp037")


HNDLINKA_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDLINKA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-B-ERROR    PIC S9(4) COMP.
       01  WS-CA.
           05  WS-CA-B-ERROR PIC S9(4) COMP.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) END-EXEC.
           CALL 'HNDLINKB' USING BY REFERENCE WS-B-ERROR.
           MOVE WS-B-ERROR TO WS-CA-B-ERROR.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-A.
           EXEC CICS RETURN END-EXEC.
"""

# Not prepassed by build_cics_spec's source_prepass -- only the main source
# passed to compile_cics_program gets that (interpreter.project.coprocessor_compile.
# compile_program folds source_prepass over the main source only); a disk-resolved
# CALL callee must bring its own COPY DFHHANDLE.
HNDLINKB_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDLINKB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY DFHHANDLE.
       LINKAGE SECTION.
       01  LS-ERROR PIC S9(4) COMP.
       PROCEDURE DIVISION USING LS-ERROR.
           EXEC CICS HANDLE CONDITION ERROR(PARA-X) END-EXEC.
           MOVE DFH-HANDLER(2) TO LS-ERROR.
           EXIT PROGRAM.
       PARA-X.
           EXIT PROGRAM.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_called_subprogram_numbers_its_own_handlers(cobol_parser, tmp_path):
    """One compile_cics_program() call lowers TWO modules -- HNDLINKA (main) then
    its disk-resolved CALL callee HNDLINKB (interpreter.project.cobol_compile.
    compile_cobol lowers every module fully, one at a time, off the SAME
    CicsDialectParser). HNDLINKA's own HANDLE CONDITION NOTFND(PARA-A) must not
    shift HNDLINKB's numbering: HNDLINKB's only HANDLE CONDITION is
    ERROR(PARA-X), so it must read index 1, not 2 (which is what leaks in if
    HNDLINKA's statement is still counted when HNDLINKB is numbered)."""
    cbl_dir = tmp_path / "cbl"
    cbl_dir.mkdir()
    (cbl_dir / "HNDLINKB.cbl").write_text(HNDLINKB_SRC)

    context_holder = [CicsContext(transid="HND5", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(
        HNDLINKA_SRC.encode(),
        cobol_parser,
        spec,
        program_source_dirs=[cbl_dir],
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
