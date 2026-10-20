"""Integration: EXEC CICS condition raising and HANDLE CONDITION dispatch."""

from __future__ import annotations

import logging
import queue
import re
import struct
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.conditions import code_for
from cics.conversational import ConversationalRegion
from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.dispatcher import InputEvent, run_cics
from tests.integration.cobol_helpers import main_entry
from cics.preprocessor import CONDITION_TABLE_SLOTS, raisable_literal
from cics.types import CicsContext, DispatchKind
from cics.vsam.engine import VsamEngine
from cics.vsam.file_table import cics_files
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature

from tests.covers import covers
from tests.vsam_system import SeedCluster, build_test_system
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401
from tests.integration.cobol_helpers import installed_cics_spec

_CICS_COPYBOOKS = Path(__file__).resolve().parents[3] / "cics" / "copybooks"
_DFHHANDLE_CPY = _CICS_COPYBOOKS / "DFHHANDLE.cpy"


@pytest.fixture(autouse=True)
def _require_bridge_jar(bridge_jar):  # noqa: F811
    """Fails loudly when PROLEAP_BRIDGE_JAR is unset."""


@pytest.fixture
def cobol_parser(bridge_jar):  # noqa: F811
    runner = RealSubprocessRunner()
    return ProLeapCobolParser(
        runner, bridge_jar, copybooks=CopybookSearch(dirs=(_CICS_COPYBOOKS,))
    )


@pytest.fixture
def vsam_engine_with_acctfile(tmp_path):
    clusters = (SeedCluster("ACCTFILE", 80, 11, ()),)
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


def _copybook_capture(pattern: str) -> str:
    """The single capture of `pattern` in DFHHANDLE.cpy. Raises IndexError when
    the copybook no longer has the shape these tests guard, which is itself the
    drift this file exists to catch."""
    return re.findall(pattern, _DFHHANDLE_CPY.read_text())[0]


def _copybook_raisable_value() -> str:
    """The DFH-RAISABLE-BYTES VALUE, reassembled from its parts. The literal is
    524 bytes and a fixed-format line stops at column 72, so it is declared as
    consecutive PIC X(n) parts of one group; the table is their concatenation."""
    text = _DFHHANDLE_CPY.read_text()
    parts = re.findall(r"DFH-RAISABLE-P\d+ PIC X\((\d+)\) VALUE\s+'([NY]+)'", text)
    assert all(int(width) == len(value) for width, value in parts)
    return "".join(value for _, value in parts)


def test_the_copybook_literal_matches_the_condition_table():
    """The copybook's Y positions are generated from conditions.py. This reads the
    committed copybook, not a recomputation, so a stale paste cannot pass."""
    assert _copybook_raisable_value() == raisable_literal()


def test_the_copybook_table_sizes_match_the_condition_table():
    """One slot per DFHRESP code the runtime can put in EIBRESP, and twice the
    bytes for the handler area because S9(4) COMP is two bytes per slot. A code
    above the largest one the copybook was generated for would index out of
    bounds, which resolve_field_ref does not check."""
    slots = CONDITION_TABLE_SLOTS
    assert len(_copybook_raisable_value()) == slots
    assert int(_copybook_capture(r"DFH-RAISABLE OCCURS (\d+) TIMES")) == slots
    assert int(_copybook_capture(r"DFH-HANDLER-BYTES PIC X\((\d+)\)")) == slots * 2
    assert int(_copybook_capture(r"DFH-HANDLER OCCURS (\d+) TIMES")) == slots


def test_no_copybook_line_runs_past_column_72():
    """Fixed format discards columns 73-80: a line over the margin silently loses
    its tail, and a truncated VALUE literal shifts every slot after it."""
    overlong = [
        line for line in _DFHHANDLE_CPY.read_text().splitlines() if len(line) > 72
    ]
    assert overlong == []


COBOL_READS_ITS_OWN_TABLE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDPROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-NOTFND   PIC X.
           05  WS-CA-NORMAL   PIC X.
           05  WS-CA-MAPFAIL  PIC X.
           05  WS-CA-DISABLED PIC X.
           05  WS-CA-LAST     PIC X.
       PROCEDURE DIVISION.
           MOVE DFH-RAISABLE(14)  TO WS-CA-NOTFND.
           MOVE DFH-RAISABLE(1)   TO WS-CA-NORMAL.
           MOVE DFH-RAISABLE(37)  TO WS-CA-MAPFAIL.
           MOVE DFH-RAISABLE(85)  TO WS-CA-DISABLED.
           MOVE DFH-RAISABLE(524) TO WS-CA-LAST.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_the_injected_table_is_visible_to_the_program(cobol_parser):
    """DFH-RAISABLE(14) is NOTFND (code 13, 1-based) and must be Y; slot 1 is
    NORMAL and must not be; slot 37 is MAPFAIL. Slot 85 is DISABLED — the code
    VsamEngine returns for a file with no FCT entry, and the one that used to
    fall off a 37-slot table. Slot 524 is the last, the subscript a wrong OCCURS
    count would run past."""
    context_holder = [CicsContext(transid="HND0", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec, builtins = installed_cics_spec(context_holder, result_holder)
    program = compile_cics_program(
        COBOL_READS_ITS_OWN_TABLE.encode(), cobol_parser, spec
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=builtins,
    )

    assert result.commarea[0:1] == "Y".encode("cp037")
    assert result.commarea[1:2] == "N".encode("cp037")
    assert result.commarea[2:3] == "Y".encode("cp037")
    assert result.commarea[3:4] == "Y".encode("cp037")
    assert result.commarea[4:5] == "N".encode("cp037")


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
    spec, builtins = installed_cics_spec(context_holder, result_holder)
    program = compile_cics_program(
        COBOL_HANDLE_WRITES_THE_SLOT.encode(), cobol_parser, spec
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=builtins,
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
    spec, builtins = installed_cics_spec(context_holder, result_holder)
    program = compile_cics_program(
        COBOL_MULTI_CONDITION_HANDLE.encode(), cobol_parser, spec
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=builtins,
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
    spec, builtins = installed_cics_spec(context_holder, result_holder)
    program = compile_cics_program(
        COBOL_OVERRIDE_AND_IGNORE.encode(), cobol_parser, spec
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=builtins,
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
           05  WS-CA-TRANSIDERR   PIC X.
           05  WS-CA-NEIGHBOUR    PIC X.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) END-EXEC.
           MOVE DFH-RAISABLE(14) TO WS-CA-AFTER-HANDLE.
           EXEC CICS IGNORE CONDITION NOTFND END-EXEC.
           MOVE DFH-RAISABLE(14) TO WS-CA-AFTER-IGNORE.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-A) END-EXEC.
           MOVE DFH-RAISABLE(14) TO WS-CA-AFTER-AGAIN.
           EXEC CICS HANDLE CONDITION TRANSIDERR(PARA-A) END-EXEC.
           MOVE DFH-RAISABLE(29) TO WS-CA-TRANSIDERR.
           MOVE DFH-RAISABLE(23) TO WS-CA-NEIGHBOUR.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-A.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_ignore_clears_the_raisable_flag_and_handle_restores_it(cobol_parser):
    """The raisable flag is what separates "ignored" from "never registered", and
    it does not depend on the label map, so this holds before Task 5.

    TRANSIDERR is the discriminating case: it is a real condition with a DFHRESP
    code but is not in RAISABLE, so HANDLE must leave its flag 'N' rather than
    silently widening what this runtime raises. LENGERR's slot is read untouched
    to show the subscripted writes land on one slot and do not smear."""
    context_holder = [CicsContext(transid="HND3", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec, builtins = installed_cics_spec(context_holder, result_holder)
    program = compile_cics_program(COBOL_RAISABLE_FLAG.encode(), cobol_parser, spec)

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=builtins,
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

# No COPY DFHEIBLK or COPY DFHHANDLE: the source_prepass injects both into a
# disk-resolved CALL callee as it does into the main program.
HNDLINKB_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDLINKB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
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
    spec, builtins = installed_cics_spec(context_holder, result_holder)
    program = compile_cics_program(
        HNDLINKA_SRC.encode(),
        cobol_parser,
        spec,
        source_search_dirs=[cbl_dir],
    )

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=builtins,
    )

    assert result.commarea[0:2] == struct.pack(">h", 1)


COBOL_UNHANDLED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDUNH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       PROCEDURE DIVISION.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_an_unhandled_condition_abends(cobol_parser, vsam_engine_with_acctfile):
    """A READ that misses, with no HANDLE registered and no RESP coded, abends
    rather than falling through to RETURN on an untouched record area."""
    context_holder = [CicsContext(transid="HND6", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec, builtins = installed_cics_spec(
        context_holder, result_holder, vsam_engine=vsam_engine_with_acctfile
    )
    program = compile_cics_program(COBOL_UNHANDLED.encode(), cobol_parser, spec)

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=builtins,
    )

    assert result.kind == DispatchKind.ABEND
    assert result.abcode == "AEIZ"


COBOL_HANDLED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDCORP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       01  WS-CA         PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-MISSING) END-EXEC.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           MOVE 'NOTTAKEN' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-MISSING.
           MOVE 'HANDLED0' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_registered_handler_takes_control(cobol_parser, vsam_engine_with_acctfile):
    """The scenario the whole feature exists for: a READ that misses transfers to
    the HANDLE CONDITION NOTFND paragraph. The NOTTAKEN write on the fall-through
    path is the discriminator — the commarea says which path ran."""
    context_holder = [CicsContext(transid="HND7", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec, builtins = installed_cics_spec(
        context_holder, result_holder, vsam_engine=vsam_engine_with_acctfile
    )
    program = compile_cics_program(COBOL_HANDLED.encode(), cobol_parser, spec)

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=builtins,
    )

    assert result.commarea == "HANDLED0".encode("cp037")


COBOL_RESP_SUPPRESSES = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDRESP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       01  WS-RESP       PIC S9(8) COMP.
       01  WS-CA.
           05  WS-CA-TAG   PIC X(8).
           05  WS-CA-RESP  PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-MISSING) END-EXEC.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
               RESP(WS-RESP) END-EXEC.
           MOVE 'INLINE00' TO WS-CA-TAG.
           MOVE EIBRESP TO WS-CA-RESP.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-MISSING.
           MOVE 'HANDLED0' TO WS-CA-TAG.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


COBOL_NOHANDLE_SUPPRESSES = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDNOH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       01  WS-CA.
           05  WS-CA-TAG   PIC X(8).
           05  WS-CA-RESP  PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-MISSING) END-EXEC.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
               NOHANDLE END-EXEC.
           MOVE 'INLINE00' TO WS-CA-TAG.
           MOVE EIBRESP TO WS-CA-RESP.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-MISSING.
           MOVE 'HANDLED0' TO WS-CA-TAG.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


def _run_source(source, transid, cobol_parser, vsam_engine):
    context_holder = [CicsContext(transid=transid, commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec, builtins = installed_cics_spec(
        context_holder, result_holder, vsam_engine=vsam_engine
    )
    program = compile_cics_program(source.encode(), cobol_parser, spec)
    return run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=builtins,
    )


@covers(CobolFeature.EXEC_CICS)
def test_resp_suppresses_the_raise(cobol_parser, vsam_engine_with_acctfile):
    """RESP is the program's undertaking to check the code inline, so the same
    failing READ under a registered NOTFND handler must fall through — and
    EIBRESP must still hold 13 for the inline check to read."""
    result = _run_source(
        COBOL_RESP_SUPPRESSES, "HND8", cobol_parser, vsam_engine_with_acctfile
    )

    assert result.commarea[0:8] == "INLINE00".encode("cp037")
    assert result.commarea[8:12] == struct.pack(">i", code_for("NOTFND"))


@covers(CobolFeature.EXEC_CICS)
def test_nohandle_suppresses_the_raise(cobol_parser, vsam_engine_with_acctfile):
    """NOHANDLE is RESP's bare form: no handler dispatch, EIBRESP still written."""
    result = _run_source(
        COBOL_NOHANDLE_SUPPRESSES, "HND9", cobol_parser, vsam_engine_with_acctfile
    )

    assert result.commarea[0:8] == "INLINE00".encode("cp037")
    assert result.commarea[8:12] == struct.pack(">i", code_for("NOTFND"))


COBOL_HANDLE_NOT_EXECUTED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDCOND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       01  WS-FLAG       PIC X VALUE 'N'.
       01  WS-CA         PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
           IF WS-FLAG = 'Y'
               EXEC CICS HANDLE CONDITION NOTFND(PARA-MISSING) END-EXEC
           END-IF.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           MOVE 'NOTTAKEN' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-MISSING.
           MOVE 'HANDLED0' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_handle_that_never_executes_leaves_the_condition_unhandled(
    cobol_parser, vsam_engine_with_acctfile
):
    """Registration is a runtime write, not a compile-time declaration: a HANDLE
    CONDITION inside a branch that is not taken leaves slot 14 at zero, so the
    miss abends even though the paragraph exists and was numbered."""
    result = _run_source(
        COBOL_HANDLE_NOT_EXECUTED, "HNDA", cobol_parser, vsam_engine_with_acctfile
    )

    assert result.kind == DispatchKind.ABEND
    assert result.abcode == "AEIZ"


COBOL_UNCONFIGURED_FILE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDNOFCT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80) VALUE SPACES.
       01  WS-KEY        PIC X(11) VALUE '00000000001'.
       PROCEDURE DIVISION.
           EXEC CICS READ FILE('NOSUCHFL') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-REC) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_read_on_a_file_with_no_fct_entry_abends(
    cobol_parser, vsam_engine_with_acctfile
):
    """DISABLED (84) is what VsamEngine returns for a file the FCT does not
    define. It used to subscript a 37-slot table 48 bytes past its end, read
    LOW-VALUES instead of 'Y' and raise nothing, so the program went on to use
    a record area the READ never wrote. Now it raises, and with no handler it
    abends."""
    result = _run_source(
        COBOL_UNCONFIGURED_FILE, "HNDB", cobol_parser, vsam_engine_with_acctfile
    )

    assert result.kind == DispatchKind.ABEND
    assert result.abcode == "AEIZ"


COBOL_UNCONFIGURED_FILE_RESP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDNOFCR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80) VALUE SPACES.
       01  WS-KEY        PIC X(11) VALUE '00000000001'.
       01  WS-RESP       PIC S9(8) COMP.
       01  WS-CA.
           05  WS-CA-TAG   PIC X(8).
           05  WS-CA-RESP  PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS READ FILE('NOSUCHFL') INTO(WS-REC) RIDFLD(WS-KEY)
               RESP(WS-RESP) END-EXEC.
           MOVE 'INLINE00' TO WS-CA-TAG.
           MOVE WS-RESP TO WS-CA-RESP.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_an_unconfigured_file_still_reports_inline_under_resp(
    cobol_parser, vsam_engine_with_acctfile
):
    """Raising DISABLED must not take the choice away from a program that codes
    RESP: it checks the code itself, so the READ falls through with 84 in hand."""
    result = _run_source(
        COBOL_UNCONFIGURED_FILE_RESP, "HNDC", cobol_parser, vsam_engine_with_acctfile
    )

    assert result.commarea[0:8] == "INLINE00".encode("cp037")
    assert result.commarea[8:12] == struct.pack(">i", code_for("DISABLED"))


COBOL_HANDLER_TARGET_MISSING = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDGHOST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA         PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(NO-SUCH-PARA) END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-REAL.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_handler_naming_no_paragraph_is_rejected_at_compile_time(cobol_parser):
    """build_cfg wires an edge only for a label it knows, so a dispatcher branch
    to an undefined para_ label produces no edge at all: the task would neither
    handle nor abend, it would simply end. The compile must refuse instead."""
    context_holder = [CicsContext(transid="HNDD", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec, builtins = installed_cics_spec(context_holder, result_holder)

    with pytest.raises(NotImplementedError) as excinfo:
        compile_cics_program(COBOL_HANDLER_TARGET_MISSING.encode(), cobol_parser, spec)

    assert "NOTFND(NO-SUCH-PARA)" in str(excinfo.value)


COBOL_IGNORE_CONTINUES_INLINE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDIGN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       01  WS-CA.
           05  WS-CA-TAG   PIC X(8).
           05  WS-CA-RESP  PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(PARA-MISSING) END-EXEC.
           EXEC CICS IGNORE CONDITION NOTFND END-EXEC.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           MOVE 'INLINE00' TO WS-CA-TAG.
           MOVE EIBRESP TO WS-CA-RESP.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-MISSING.
           MOVE 'HANDLED0' TO WS-CA-TAG.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_ignore_condition_lets_the_failed_command_continue_inline(
    cobol_parser, vsam_engine_with_acctfile
):
    """IGNORE CONDITION means "take no action", which is neither the registered
    handler nor the default abend: the READ misses, EIBRESP still says NOTFND,
    and the next statement runs. The earlier HANDLE is what IGNORE has to beat."""
    result = _run_source(
        COBOL_IGNORE_CONTINUES_INLINE, "HNDE", cobol_parser, vsam_engine_with_acctfile
    )

    assert result.commarea[0:8] == "INLINE00".encode("cp037")
    assert result.commarea[8:12] == struct.pack(">i", code_for("NOTFND"))


COBOL_HANDLE_UNRAISED_CONDITION = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDENDF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA         PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION ENDFILE(PARA-EOF) END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-EOF.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_handler_for_an_unraised_condition_is_reported(cobol_parser, caplog):
    """ENDFILE is not in RAISABLE, so its handler can never be dispatched to.
    The limitation is tracked; registering the handler in silence is not — a
    READNEXT loop written against it would loop past the end of the file."""
    context_holder = [CicsContext(transid="HNDF", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    spec, builtins = installed_cics_spec(context_holder, result_holder)

    with caplog.at_level(logging.WARNING, logger="cics.strategy"):
        compile_cics_program(
            COBOL_HANDLE_UNRAISED_CONDITION.encode(), cobol_parser, spec
        )

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    assert [w for w in warnings if "ENDFILE" in w and "PARA-EOF" in w] != []


COBOL_CONVERSATIONAL_RECEIVE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDCONV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CONVMAPI.
           05  FLD1L PIC S9(4) COMP.
           05  FLD1F PIC X.
           05  FLD1I PIC X(8).
       01  WS-CA         PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION MAPFAIL(PARA-NOMAP) END-EXEC.
           EXEC CICS RECEIVE MAP('CONVMAP') INTO(CONVMAPI) END-EXEC.
           MOVE 'RECEIVED' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-NOMAP.
           MOVE 'MAPFAIL0' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


def _conversational_region(cobol_parser, transid, source=COBOL_CONVERSATIONAL_RECEIVE):
    context_holder = [CicsContext(transid=transid, commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    screen_queue: queue.Queue = queue.Queue()
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        result_holder=result_holder,
        screen_queue=screen_queue,
        input_queue=queue.Queue(),
    )
    spec = build_cics_spec(conversational=True)
    program = compile_cics_program(source.encode(), cobol_parser, spec)
    return ConversationalRegion(
        program,
        transid,
        screen_queue=screen_queue,
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=runtime.builtins,
    )


@covers(CobolFeature.EXEC_CICS)
def test_a_conversational_receive_with_no_input_raises_mapfail(cobol_parser):
    """The conversational RECEIVE MAP path used to return before writing EIBRESP
    at all, so the same source raised MAPFAIL when compiled for the blocking
    dispatcher and silently carried on when compiled conversational."""
    region = _conversational_region(cobol_parser, "HNDG")
    region.start()

    region.send(None)

    assert region.result.commarea == "MAPFAIL0".encode("cp037")


@covers(CobolFeature.EXEC_CICS)
def test_a_conversational_receive_with_input_runs_on(cobol_parser):
    """The raise tail must leave the normal path alone: an input event applied at
    the resume is EIBRESP 0, so the statement after the RECEIVE runs."""
    region = _conversational_region(cobol_parser, "HNDH")
    region.start()

    region.send(InputEvent(fields={"FLD1": "ABC"}, eibaid="\x7d"))

    assert region.result.commarea == "RECEIVED".encode("cp037")


COBOL_HANDLER_NAMED_IN_LOWER_CASE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDCASE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       01  WS-CA         PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE CONDITION NOTFND(para-missing) END-EXEC.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC.
           MOVE 'NOTTAKEN' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       Para-Missing.
           MOVE 'HANDLED0' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


def _duplicated_handler_target(registers_and_raises: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDDUP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       01  WS-CA         PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
       SEC-A SECTION.
       A-START.
           GO TO SEC-B.
       ERR-PARA.
           MOVE 'WRONGSEC' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       SEC-B SECTION.
       B-START.
{registers_and_raises}
           MOVE 'NOTTAKEN' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       ERR-PARA.
           MOVE 'HANDLED0' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


_NOTFND_TO_ERR_PARA = """\
           EXEC CICS HANDLE CONDITION NOTFND(ERR-PARA) END-EXEC.
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC."""
_ABEND_TO_ERR_PARA = """\
           EXEC CICS HANDLE ABEND LABEL(ERR-PARA) END-EXEC.
           EXEC CICS ABEND ABCODE('AAAA') END-EXEC."""


@covers(CobolFeature.EXEC_CICS)
@pytest.mark.parametrize(
    "source",
    [
        COBOL_HANDLER_NAMED_IN_LOWER_CASE,
        _duplicated_handler_target(_NOTFND_TO_ERR_PARA),
        _duplicated_handler_target(_ABEND_TO_ERR_PARA),
    ],
    ids=["lower-case-name", "handle-condition-duplicated", "handle-abend-duplicated"],
)
def test_a_handler_target_resolves_as_a_cobol_procedure_reference_does(
    source, cobol_parser, vsam_engine_with_acctfile
):
    """A handler names a procedure the way PERFORM or GO TO does: case folds,
    and a paragraph name declared in two sections means the one in the section
    of the HANDLE statement. WRONGSEC is the other section's paragraph."""
    result = _run_source(source, "HND9", cobol_parser, vsam_engine_with_acctfile)

    assert (result.kind, result.commarea) == (
        DispatchKind.RETURN,
        "HANDLED0".encode("cp037"),
    )


def _aid_handling(receive: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HNDAID.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CONVMAPI.
           05  FLD1L PIC S9(4) COMP.
           05  FLD1F PIC X.
           05  FLD1I PIC X(8).
       01  WS-RESP       PIC S9(8) COMP.
       01  WS-CA         PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE AID PF3(PARA-PF3) ANYKEY(PARA-ANY)
           END-EXEC.
           EXEC CICS HANDLE CONDITION MAPFAIL(PARA-NOMAP) END-EXEC.
{receive}
           MOVE 'RECEIVED' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-PF3.
           MOVE 'PF3TAKEN' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-ANY.
           MOVE 'ANYKEY00' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-NOMAP.
           MOVE 'MAPFAIL0' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


_RECEIVE = """\
           EXEC CICS RECEIVE MAP('CONVMAP') INTO(CONVMAPI) END-EXEC."""

_RECEIVE_WITH_RESP = """\
           EXEC CICS RECEIVE MAP('CONVMAP') INTO(CONVMAPI)
               RESP(WS-RESP) END-EXEC."""

_PF3_UNLABELLED_BEFORE_RECEIVE = """\
           EXEC CICS HANDLE AID PF3 END-EXEC.
           EXEC CICS RECEIVE MAP('CONVMAP') INTO(CONVMAPI) END-EXEC."""


@pytest.mark.parametrize(
    ("receive", "aid", "taken"),
    [
        pytest.param(_RECEIVE, "\xf3", "PF3TAKEN", id="named-key"),
        pytest.param(_RECEIVE, "\xf5", "ANYKEY00", id="anykey-catches-another-pf"),
        pytest.param(_RECEIVE, "\x6d", "ANYKEY00", id="anykey-catches-clear"),
        pytest.param(_RECEIVE, "\x7d", "RECEIVED", id="anykey-leaves-enter"),
        pytest.param(_RECEIVE_WITH_RESP, "\xf3", "RECEIVED", id="resp-suppresses"),
        pytest.param(
            _PF3_UNLABELLED_BEFORE_RECEIVE, "\xf3", "RECEIVED", id="unlabelled-ignores"
        ),
    ],
)
@covers(CobolFeature.EXEC_CICS)
def test_handle_aid_branches_on_the_key_that_ended_the_receive(
    cobol_parser, receive, aid, taken
):
    region = _conversational_region(cobol_parser, "HNDA", _aid_handling(receive))
    region.start()

    region.send(InputEvent(fields={"FLD1": "ABC"}, eibaid=aid))

    assert region.result.commarea == taken.encode("cp037")
