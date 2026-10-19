"""Integration: EXEC CICS interval control — START and RETRIEVE scenarios.

Each scenario drives complete COBOL through the real compile + region path and
asserts DECODED DATA, never that a branch ran (see
docs/records/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md).
"""

# ruff: noqa: I001
# The python-fp-lint pre-commit hook and every ruff we can run against this file
# disagree about the import order: ruff reports it clean, the hook reports I001,
# and the two want opposite groupings for `cics` (third-party from the repo root,
# first-party under cicada/pyproject.toml). Suppressed here rather than churning
# the block to satisfy a checker that cannot be satisfied from both directions.

from __future__ import annotations

import queue
from pathlib import Path

import pytest
from cics.bootstrap import compile_cics_program
from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.dispatcher import CicsRegion, InputEvent, run_cics
from tests.integration.cobol_helpers import main_entry
from cics.interval import RejectReason, StartQueue, StartRequest
from cics.preprocessor import apply_cics_prepass
from cics.statements import CicsDialectParser
from cics.strategy import CicsLoweringStrategy
from cics.types import CicsContext, DispatchKind
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.cobol_frontend import CobolFrontend
from interpreter.cobol.features import CobolFeature
from interpreter.func_name import FuncName
from interpreter.instructions import Return_

from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

_CICS_COPYBOOKS = Path(__file__).resolve().parents[3] / "cics" / "copybooks"


@pytest.fixture(autouse=True)
def _require_bridge_jar(bridge_jar):  # noqa: F811
    """Fails loudly when PROLEAP_BRIDGE_JAR is unset."""


@pytest.fixture
def cobol_parser(bridge_jar):  # noqa: F811
    runner = RealSubprocessRunner()
    return ProLeapCobolParser(
        runner, bridge_jar, copybooks=CopybookSearch(dirs=(_CICS_COPYBOOKS,))
    )


COBOL_EIBTRMID = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TERMPRB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(4)  VALUE SPACES.
       PROCEDURE DIVISION.
           MOVE EIBTRMID TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_eibterm_is_readable_by_the_program(cobol_parser):
    """S11: EIBTRMID reaches the program, which START TERMID(EIBTRMID) needs."""
    context_holder = [
        CicsContext(transid="TRM0", commarea=b"", eibaid="\x7d", termid="T001")
    ]
    result_holder: list = [None]
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        result_holder=result_holder,
    )
    spec = build_cics_spec()
    program = compile_cics_program(COBOL_EIBTRMID.encode(), cobol_parser, spec)

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=runtime.builtins,
    )

    assert result.kind == DispatchKind.RETURN
    assert result.commarea == "T001".encode("cp037")


COBOL_START_A = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-START-DATA.
           05  WS-SD-KEY   PIC X(6)  VALUE 'ACCT01'.
           05  WS-SD-AMT   PIC X(8)  VALUE '00012345'.
       01  WS-AFTER        PIC X(8)  VALUE SPACES.
       01  WS-CA           PIC X(8)  VALUE SPACES.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB')
                           TERMID(EIBTRMID)
                           FROM(WS-START-DATA)
                           LENGTH(14)
           END-EXEC.
           MOVE 'RANAFTER' TO WS-AFTER.
           MOVE WS-AFTER   TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


def _spec_with_queue(context_holder, result_holder, start_queue, transid_map):
    runtime = install_cics_runtime(
        context_holder,
        program_cache={},
        result_holder=result_holder,
        start_queue=start_queue,
        transid_to_program=transid_map,
        region_termid="T001",
    )
    return build_cics_spec(), runtime.builtins


@covers(CobolFeature.EXEC_CICS)
def test_start_queues_the_request_and_the_program_keeps_running(cobol_parser):
    """S1 assertions 1 and 3, without a region: the request lands AND the
    statement after the START executes."""
    context_holder = [
        CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001")
    ]
    result_holder: list = [None]
    start_queue = StartQueue()
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, {"SRTB": "STARTB"}
    )
    program = compile_cics_program(COBOL_START_A.encode(), cobol_parser, spec)

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

    assert start_queue.pending == (
        StartRequest(
            transid="SRTB",
            data="ACCT01".encode("cp037") + "00012345".encode("cp037"),
            termid="T001",
        ),
    )
    # The MOVE after the START ran: START is not a task end.
    assert result.commarea == "RANAFTER".encode("cp037")


@covers(CobolFeature.EXEC_CICS)
def test_start_lowering_emits_no_return(cobol_parser):
    """The invariant no passing scenario can observe: if START ever emits a
    Return_ again, the program silently stops there."""
    strategy = CicsLoweringStrategy(
        conversational=False, handler_source=[], unsupported_verbs=set()
    )
    frontend = CobolFrontend(
        cobol_parser=cobol_parser,
        extension_strategies=[strategy],
        dialect_parsers=[CicsDialectParser()],
    )
    instructions = frontend.lower(apply_cics_prepass(COBOL_START_A).encode())

    start_calls = [
        n
        for n, inst in enumerate(instructions)
        if getattr(inst, "func_name", None) == FuncName("__cics_start")
    ]
    assert len(start_calls) == 1, f"expected one __cics_start call, got {start_calls}"

    task_end = next(
        n
        for n, inst in enumerate(instructions)
        if n > start_calls[0]
        and getattr(inst, "func_name", None) == FuncName("__cics_task_end_hook")
    )
    returns_through_task_end = [
        n
        for n, inst in enumerate(instructions)
        if start_calls[0] <= n <= task_end + 1
        and isinstance(inst, Return_)
        and not inst.implicit
    ]
    assert returns_through_task_end == [task_end + 1], (
        f"expected the only Return_ from START to the trailing RETURN to be the "
        f"RETURN's own, got {returns_through_task_end} — START must not emit its own"
    )


COBOL_RETRIEVE_NO_DATA = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RTVNONE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN           PIC X(8)  VALUE 'UNTOUCHD'.
       01  WS-LEN          PIC S9(4) COMP VALUE 8.
       01  WS-CA.
           05  WS-CA-RESP  PIC S9(8) COMP.
           05  WS-CA-IN    PIC X(8).
       PROCEDURE DIVISION.
           EXEC CICS RETRIEVE INTO(WS-IN) LENGTH(WS-LEN) END-EXEC.
           MOVE EIBRESP TO WS-CA-RESP.
           MOVE WS-IN   TO WS-CA-IN.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_retrieve_with_no_start_data_yields_enddata(cobol_parser):
    """S3: a task nobody started gets ENDDATA and its INTO area is UNCHANGED."""
    import struct

    context_holder = [
        CicsContext(transid="RTV0", commarea=b"", eibaid="\x7d", termid="T001")
    ]
    result_holder: list = [None]
    start_queue = StartQueue()
    spec, builtins = _spec_with_queue(context_holder, result_holder, start_queue, {})
    program = compile_cics_program(COBOL_RETRIEVE_NO_DATA.encode(), cobol_parser, spec)

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

    assert result.commarea[:4] == struct.pack(">i", 29)  # DFHRESP(ENDDATA)
    assert result.commarea[4:12] == "UNTOUCHD".encode("cp037")


COBOL_START_B = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN.
           05  WS-IN-KEY   PIC X(6)  VALUE SPACES.
           05  WS-IN-AMT   PIC X(8)  VALUE SPACES.
       01  WS-LEN          PIC S9(4) COMP VALUE 14.
       01  WS-CA.
           05  WS-CA-CALEN PIC S9(4) COMP.
           05  WS-CA-KEY   PIC X(6).
           05  WS-CA-AMT   PIC X(8).
       PROCEDURE DIVISION.
           MOVE EIBCALEN TO WS-CA-CALEN.
           EXEC CICS RETRIEVE INTO(WS-IN) LENGTH(WS-LEN) END-EXEC.
           MOVE WS-IN-KEY TO WS-CA-KEY.
           MOVE WS-IN-AMT TO WS-CA-AMT.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_started_task_runs_and_retrieves_the_data(cobol_parser):
    """S1: the corpus idiom end to end through a region."""
    import struct

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTA", "SRTB": "STARTB"}
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
    )
    program_cache = {
        "STARTA": compile_cics_program(COBOL_START_A.encode(), cobol_parser, spec),
        "STARTB": compile_cics_program(COBOL_START_B.encode(), cobol_parser, spec),
    }

    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        builtins=builtins,
    )

    first = region.start("SRTA", input_event=InputEvent())
    assert first.kind == DispatchKind.RETURN
    assert first.commarea == "RANAFTER".encode("cp037")
    assert region.done is False, "a runnable START was pending — not done"
    assert region.transid == "SRTB"

    # A started task needs no terminal input, so no input_event — the same
    # convention CicsRegion already states for the turn after an XCTL.
    second = region.step()

    assert second.kind == DispatchKind.RETURN
    assert second.commarea[0:2] == struct.pack(">h", 0)
    assert second.commarea[2:8] == "ACCT01".encode("cp037")
    assert second.commarea[8:16] == "00012345".encode("cp037")
    assert region.done is True


COBOL_START_THEN_XCTL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-START-DATA.
           05  WS-SD-KEY   PIC X(6)  VALUE 'ACCT01'.
           05  WS-SD-AMT   PIC X(8)  VALUE '00012345'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB')
                           TERMID(EIBTRMID)
                           FROM(WS-START-DATA)
                           LENGTH(14)
           END-EXEC.
           EXEC CICS XCTL PROGRAM('XCTLTGT') END-EXEC.
"""

COBOL_XCTL_TARGET = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XCTLTGT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'XCTLDONE'.
       PROCEDURE DIVISION.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_xctl_after_a_start_runs_the_xctl_target_first(cobol_parser):
    """An XCTL is not a task end: the started task must wait for the issuing task
    to actually END, so the XCTL'd program runs before it."""
    import struct

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTX": "STARTX", "SRTB": "STARTB"}
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
    )
    program_cache = {
        "STARTX": compile_cics_program(
            COBOL_START_THEN_XCTL.encode(), cobol_parser, spec
        ),
        "XCTLTGT": compile_cics_program(COBOL_XCTL_TARGET.encode(), cobol_parser, spec),
        "STARTB": compile_cics_program(COBOL_START_B.encode(), cobol_parser, spec),
    }

    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        builtins=builtins,
    )

    first = region.start("SRTX", input_event=InputEvent())
    assert first.kind == DispatchKind.XCTL
    assert region.transid == "SRTX", "XCTL carries the transid — same task"

    second = region.step()
    assert second.kind == DispatchKind.RETURN
    assert second.commarea == "XCTLDONE".encode("cp037")

    # Only NOW has the task ended, so the started task becomes runnable.
    assert region.transid == "SRTB"
    third = region.step()
    assert third.commarea[0:2] == struct.pack(">h", 0)
    assert third.commarea[2:8] == "ACCT01".encode("cp037")
    assert region.done is True


COBOL_START_NON_TERMINAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'QUEUEDIT'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTM') END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""

COBOL_STARTED_XCTL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTM.
       PROCEDURE DIVISION.
           EXEC CICS XCTL PROGRAM('TERMPRB') END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_xctl_from_a_non_terminal_started_task_keeps_its_empty_terminal(cobol_parser):
    """An XCTL keeps the SAME task, so it keeps that task's terminal: a task
    started with no TERMID must still see a blank EIBTRMID after the transfer."""
    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTN": "STARTN", "SRTM": "STARTM"}
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
    )
    program_cache = {
        "STARTN": compile_cics_program(
            COBOL_START_NON_TERMINAL.encode(), cobol_parser, spec
        ),
        "STARTM": compile_cics_program(COBOL_STARTED_XCTL.encode(), cobol_parser, spec),
        "TERMPRB": compile_cics_program(COBOL_EIBTRMID.encode(), cobol_parser, spec),
    }

    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        builtins=builtins,
    )

    first = region.start("SRTN", input_event=InputEvent())
    assert first.commarea == "QUEUEDIT".encode("cp037")
    assert region.transid == "SRTM"

    second = region.step()
    assert second.kind == DispatchKind.XCTL

    third = region.step()
    assert third.kind == DispatchKind.RETURN
    assert third.commarea == "    ".encode("cp037")
    assert region.done is True


COBOL_START_THEN_TRANSID = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTA2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-START-DATA.
           05  WS-SD-KEY   PIC X(6)  VALUE 'ACCT01'.
           05  WS-SD-AMT   PIC X(8)  VALUE '00012345'.
       01  WS-CA           PIC X(8)  VALUE 'FROMSRTA'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB')
                           TERMID(EIBTRMID)
                           FROM(WS-START-DATA)
                           LENGTH(14)
           END-EXEC.
           EXEC CICS RETURN TRANSID('SRTC') COMMAREA(WS-CA) END-EXEC.
"""

COBOL_NEXT_TRANSID = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE SPACES.
       PROCEDURE DIVISION.
           MOVE 'RANSRTC0' TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_started_task_runs_before_the_next_transid(cobol_parser):
    """S2: runnable first — SRTB needs no input, SRTC does, and the next-transid
    slot survives the started task."""
    import struct

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTA2", "SRTB": "STARTB", "SRTC": "STARTC"}
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
    )
    program_cache = {
        "STARTA2": compile_cics_program(
            COBOL_START_THEN_TRANSID.encode(), cobol_parser, spec
        ),
        "STARTB": compile_cics_program(COBOL_START_B.encode(), cobol_parser, spec),
        "STARTC": compile_cics_program(COBOL_NEXT_TRANSID.encode(), cobol_parser, spec),
    }

    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        builtins=builtins,
    )

    region.start("SRTA", input_event=InputEvent())
    assert region.transid == "SRTB", "the started task must run before SRTC"

    # A started task needs no terminal input, so no input_event — same
    # convention CicsRegion states for the turn after an XCTL.
    started = region.step()
    assert started.commarea[0:2] == struct.pack(">h", 0)
    assert started.commarea[2:8] == "ACCT01".encode("cp037")
    assert region.transid == "SRTC", "the next-transid must survive the started task"
    assert region.done is False

    last = region.step(input_event=InputEvent())
    assert last.commarea == "RANSRTC0".encode("cp037")
    assert region.done is True


COBOL_START_BAD_TRANSID = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTBT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('ZZZZ') TERMID(EIBTRMID) END-EXEC.
           MOVE EIBRESP TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""

COBOL_START_BAD_TERMID = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTBM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB') TERMID('P001') END-EXEC.
           MOVE EIBRESP TO WS-CA.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


def _run_one(cobol_parser, source, transid_map, start_queue):
    context_holder = [
        CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001")
    ]
    result_holder: list = [None]
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
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
def test_start_to_an_unknown_transid_yields_transiderr(cobol_parser):
    """S6."""
    import struct

    start_queue = StartQueue()
    result = _run_one(
        cobol_parser, COBOL_START_BAD_TRANSID, {"SRTB": "STARTB"}, start_queue
    )

    assert result.commarea[:4] == struct.pack(">i", 28)  # TRANSIDERR
    assert start_queue.pending == ()
    assert start_queue.rejected[0][1] == RejectReason.UNKNOWN_TRANSID


@covers(CobolFeature.EXEC_CICS)
def test_start_for_another_terminal_yields_termiderr(cobol_parser):
    """S5: this region has no terminal P001, so the request never runs here."""
    import struct

    start_queue = StartQueue()
    result = _run_one(
        cobol_parser, COBOL_START_BAD_TERMID, {"SRTB": "STARTB"}, start_queue
    )

    assert result.commarea[:4] == struct.pack(">i", 11)  # TERMIDERR
    assert start_queue.pending == ()
    assert start_queue.rejected[0][1] == RejectReason.NO_SUCH_TERMINAL


COBOL_START_NOTERM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTNT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'FROMNTRM'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTD') END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""

COBOL_NONTERMINAL_TASK = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA.
           05  WS-CA-TRAN  PIC X(4)  VALUE SPACES.
           05  WS-CA-TERM  PIC X(4)  VALUE SPACES.
           05  WS-CA-RESP  PIC S9(8) COMP VALUE ZERO.
       PROCEDURE DIVISION.
           EXEC CICS SEND MAP('NOMAP') RESP(WS-CA-RESP) END-EXEC.
           MOVE EIBRESP  TO WS-CA-RESP.
           MOVE EIBTRNID TO WS-CA-TRAN.
           MOVE EIBTRMID TO WS-CA-TERM.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_non_terminal_started_task_runs_and_send_map_is_invreq(cobol_parser):
    """S4: a START with no TERMID runs, but terminal I/O is invalid for it.

    STARTD codes RESP on the SEND MAP, which is what makes INVREQ readable
    inline instead of a raised condition."""
    import struct

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTNT", "SRTD": "STARTD"}
    screen_queue: queue.Queue = queue.Queue()
    input_queue: queue.Queue = queue.Queue()
    runtime = install_cics_runtime(
        context_holder,
        program_cache={},
        result_holder=result_holder,
        start_queue=start_queue,
        transid_to_program=transid_map,
        region_termid="T001",
        screen_queue=screen_queue,
        input_queue=input_queue,
    )
    spec = build_cics_spec()
    program_cache = {
        "STARTNT": compile_cics_program(
            COBOL_START_NOTERM.encode(), cobol_parser, spec
        ),
        "STARTD": compile_cics_program(
            COBOL_NONTERMINAL_TASK.encode(), cobol_parser, spec
        ),
    }

    region = CicsRegion(
        program_cache,
        transid_map,
        screen_queue,
        input_queue,
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        builtins=runtime.builtins,
    )

    region.start("SRTA", input_event=InputEvent())
    assert region.transid == "SRTD"

    started = region.step()

    assert started.commarea[0:4].decode("cp037") == "SRTD"
    assert started.commarea[4:8].decode("cp037") == "    "
    assert struct.unpack(">i", started.commarea[8:12])[0] == 16  # INVREQ
    assert screen_queue.empty() is True


COBOL_NONTERMINAL_TASK_UNHANDLED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'RANAFTER'.
       PROCEDURE DIVISION.
           EXEC CICS SEND MAP('NOMAP') END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_non_terminal_send_map_without_resp_abends(cobol_parser):
    """The same invalid terminal I/O with no RESP, no NOHANDLE and no HANDLE
    CONDITION INVREQ: CICS abends the task rather than running the RETURN that
    follows, so there is no commarea to inspect."""
    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTNT", "SRTD": "STARTD"}
    screen_queue: queue.Queue = queue.Queue()
    input_queue: queue.Queue = queue.Queue()
    runtime = install_cics_runtime(
        context_holder,
        program_cache={},
        result_holder=result_holder,
        start_queue=start_queue,
        transid_to_program=transid_map,
        region_termid="T001",
        screen_queue=screen_queue,
        input_queue=input_queue,
    )
    spec = build_cics_spec()
    program_cache = {
        "STARTNT": compile_cics_program(
            COBOL_START_NOTERM.encode(), cobol_parser, spec
        ),
        "STARTD": compile_cics_program(
            COBOL_NONTERMINAL_TASK_UNHANDLED.encode(), cobol_parser, spec
        ),
    }

    region = CicsRegion(
        program_cache,
        transid_map,
        screen_queue,
        input_queue,
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        builtins=runtime.builtins,
    )

    region.start("SRTA", input_event=InputEvent())
    started = region.step()

    assert started.kind == DispatchKind.ABEND
    assert started.abcode == "AEIZ"
    assert screen_queue.empty() is True


COBOL_START_INTERVAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTIV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'FROMIVAL'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB')
                           TERMID(EIBTRMID)
                           INTERVAL(000005)
           END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_non_zero_interval_is_recorded_and_dispatched_immediately(cobol_parser):
    """S7: INTERVAL(000005) cannot be honoured (no region clock), so the request
    still runs immediately, and the delay it asked for is recorded, not silently
    dropped."""
    start_queue = StartQueue()
    result = _run_one(
        cobol_parser, COBOL_START_INTERVAL, {"SRTB": "STARTB"}, start_queue
    )

    assert result.commarea == "FROMIVAL".encode("cp037")
    assert len(start_queue.pending) == 1
    assert len(start_queue.ignored_delays) == 1
    assert start_queue.ignored_delays[0].transid == "SRTB"
    assert start_queue.ignored_delays[0].timing_text == "INTERVAL(000005)"


COBOL_START_TWICE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTTW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FIRST.
           05  FILLER      PIC X(6)  VALUE 'FIRST1'.
           05  FILLER      PIC X(8)  VALUE '00000001'.
       01  WS-SECOND.
           05  FILLER      PIC X(6)  VALUE 'SECND2'.
           05  FILLER      PIC X(8)  VALUE '00000002'.
       01  WS-CA           PIC X(8)  VALUE 'TWOSTART'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB') TERMID(EIBTRMID)
                           FROM(WS-FIRST) LENGTH(14) END-EXEC.
           EXEC CICS START TRANSID('SRTB') TERMID(EIBTRMID)
                           FROM(WS-SECOND) LENGTH(14) END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_two_starts_run_in_order_each_with_its_own_data(cobol_parser):
    """S9: two STARTs against the same TRANSID run FIFO, and each started task
    RETRIEVEs its own payload — no cross-talk between the two queued requests."""
    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTTW", "SRTB": "STARTB"}
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
    )
    program_cache = {
        "STARTTW": compile_cics_program(COBOL_START_TWICE.encode(), cobol_parser, spec),
        "STARTB": compile_cics_program(COBOL_START_B.encode(), cobol_parser, spec),
    }
    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        builtins=builtins,
    )

    region.start("SRTA", input_event=InputEvent())
    first = region.step()
    assert first.commarea[2:8] == "FIRST1".encode("cp037")
    assert first.commarea[8:16] == "00000001".encode("cp037")

    second = region.step()
    assert second.commarea[2:8] == "SECND2".encode("cp037")
    assert second.commarea[8:16] == "00000002".encode("cp037")
    assert region.done is True


COBOL_RETRIEVE_TWICE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RTVTWICE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN           PIC X(14) VALUE SPACES.
       01  WS-LEN          PIC S9(4) COMP VALUE 14.
       01  WS-CA.
           05  WS-CA-FIRST PIC X(14).
           05  WS-CA-RESP2 PIC S9(8) COMP.
       PROCEDURE DIVISION.
           EXEC CICS RETRIEVE INTO(WS-IN) LENGTH(WS-LEN) END-EXEC.
           MOVE WS-IN TO WS-CA-FIRST.
           EXEC CICS RETRIEVE INTO(WS-IN) LENGTH(WS-LEN) END-EXEC.
           MOVE EIBRESP TO WS-CA-RESP2.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_start_data_is_consumed_by_the_first_retrieve(cobol_parser):
    """S10: the second RETRIEVE in the same task gets ENDDATA — take_start_data
    is a consume, not a peek."""
    import struct

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTA", "SRTB": "RTVTWICE"}
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
    )
    program_cache = {
        "STARTA": compile_cics_program(COBOL_START_A.encode(), cobol_parser, spec),
        "RTVTWICE": compile_cics_program(
            COBOL_RETRIEVE_TWICE.encode(), cobol_parser, spec
        ),
    }
    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        builtins=builtins,
    )

    region.start("SRTA", input_event=InputEvent())
    started = region.step()

    assert started.commarea[:6] == "ACCT01".encode("cp037")
    assert started.commarea[6:14] == "00012345".encode("cp037")
    assert started.commarea[14:18] == struct.pack(">i", 29)  # ENDDATA


COBOL_START_SELF = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTLP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'LOOPING0'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTL') TERMID(EIBTRMID) END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""

COBOL_START_SELF_THEN_XCTL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTLX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'LOOPING1'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTL') TERMID(EIBTRMID) END-EXEC.
           EXEC CICS XCTL PROGRAM('XCTLEND') COMMAREA(WS-CA) END-EXEC.
"""

COBOL_XCTL_END = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XCTLEND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'ENDEDXCT'.
       PROCEDURE DIVISION.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""

COBOL_START_THEN_SELF_TRANSID = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTA3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-START-DATA.
           05  WS-SD-KEY   PIC X(6)  VALUE 'ACCT01'.
           05  WS-SD-AMT   PIC X(8)  VALUE '00012345'.
       01  WS-CA           PIC X(8)  VALUE 'FROMSRTA'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTB')
                           TERMID(EIBTRMID)
                           FROM(WS-START-DATA)
                           LENGTH(14)
           END-EXEC.
           EXEC CICS RETURN TRANSID('SRTA') COMMAREA(WS-CA) END-EXEC.
"""

# The region's cap is injectable so both halves of the runaway rule can be
# driven in a handful of program runs. The production default is 256; the code
# path under test is the same one, with a smaller number.
_TEST_CAP = 2
_STEP_BOUND = _TEST_CAP * 8


def _looping_region(cobol_parser, sources, transid_map):
    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
    )
    program_cache = {
        name: compile_cics_program(source.encode(), cobol_parser, spec)
        for name, source in sources.items()
    }
    return CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        max_consecutive_starts=_TEST_CAP,
        builtins=builtins,
    )


def _run_until_done(region):
    """Drive the region with no terminal input at all, bounded so a guard that
    fails to fire ends the test instead of hanging it."""
    turns = []
    for _ in range(_STEP_BOUND):
        if region.done:
            break
        turns.append(region.step())
    return turns


@covers(CobolFeature.EXEC_CICS)
def test_a_self_starting_transaction_hits_the_runaway_guard(cobol_parser):
    """S8: 'runnable first' has no terminal input to break the cycle, so the
    region must stop itself rather than spin."""
    transid_map = {"SRTL": "STARTLP"}
    region = _looping_region(cobol_parser, {"STARTLP": COBOL_START_SELF}, transid_map)

    region.start("SRTL", input_event=InputEvent())
    turns = _run_until_done(region)

    assert region.done is True
    assert turns[-1].kind == DispatchKind.ABEND
    assert turns[-1].abcode == "ASTL"
    # The cap counts started tasks ADOPTED and start() adopts the first, so the
    # turn that refuses the adoption is the cap-th.
    assert len(turns) == _TEST_CAP


@covers(CobolFeature.EXEC_CICS)
def test_a_start_xctl_cycle_hits_the_runaway_guard(cobol_parser):
    """S8, evasion case: an XCTL is a transfer within the same task and waits for
    no terminal input, so a START/XCTL cycle must not reset the guard's count."""
    transid_map = {"SRTL": "STARTLX"}
    region = _looping_region(
        cobol_parser,
        {"STARTLX": COBOL_START_SELF_THEN_XCTL, "XCTLEND": COBOL_XCTL_END},
        transid_map,
    )

    region.start("SRTL", input_event=InputEvent())
    turns = _run_until_done(region)

    assert region.done is True
    assert turns[-1].kind == DispatchKind.ABEND
    assert turns[-1].abcode == "ASTL"
    # Two turns per cycle — XCTLEND's RETURN, then STARTLX's XCTL — with the
    # entry task's own XCTL consumed by start().
    assert len(turns) == _TEST_CAP * 2 + 1


@covers(CobolFeature.EXEC_CICS)
def test_a_next_transid_turn_resets_the_runaway_guard(cobol_parser):
    """S8, false-positive case: a region interleaving started tasks with
    next-transid turns is doing legitimate work — the terminal input each
    next-transid turn waits for breaks the chain, so the guard must not fire
    however long the region runs."""
    import struct

    transid_map = {"SRTA": "STARTA3", "SRTB": "STARTB"}
    region = _looping_region(
        cobol_parser,
        {"STARTA3": COBOL_START_THEN_SELF_TRANSID, "STARTB": COBOL_START_B},
        transid_map,
    )

    region.start("SRTA", input_event=InputEvent())
    assert region.transid == "SRTB"

    turns = []
    for turn in range(_TEST_CAP * 4):
        assert region.done is False, "the guard fired on a chain terminal input broke"
        # Even turns run the started task (no terminal input); odd turns run the
        # next-transid task, whose terminal input is what resets the count.
        turns.append(
            region.step() if turn % 2 == 0 else region.step(input_event=InputEvent())
        )

    assert [each.kind for each in turns] == [
        DispatchKind.RETURN,
        DispatchKind.RETURN_TRANSID,
    ] * (_TEST_CAP * 2)
    assert turns[0].commarea[0:2] == struct.pack(">h", 0)
    assert turns[0].commarea[2:8] == "ACCT01".encode("cp037")
    assert turns[1].commarea == "FROMSRTA".encode("cp037")
    assert turns[-2].commarea[2:8] == "ACCT01".encode("cp037")
    assert turns[-1].commarea == "FROMSRTA".encode("cp037")
    assert region.done is False


COBOL_START_NO_FROM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STARTNF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'NOFROMOK'.
       PROCEDURE DIVISION.
           EXEC CICS START TRANSID('SRTR')
                           TERMID(EIBTRMID)
           END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_task_started_with_no_from_retrieves_enddata(cobol_parser):
    """S3 for a task that WAS started: no FROM means no start data, so RETRIEVE
    is ENDDATA and the INTO area is unchanged. The lowering passes an empty
    payload for a missing FROM, which must not read as "data of length zero"."""
    import struct

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTF": "STARTNF", "SRTR": "RTVNONE"}
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
    )
    program_cache = {
        "STARTNF": compile_cics_program(
            COBOL_START_NO_FROM.encode(), cobol_parser, spec
        ),
        "RTVNONE": compile_cics_program(
            COBOL_RETRIEVE_NO_DATA.encode(), cobol_parser, spec
        ),
    }

    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        builtins=builtins,
    )

    first = region.start("SRTF", input_event=InputEvent())
    assert first.commarea == "NOFROMOK".encode("cp037")
    assert region.transid == "SRTR"

    second = region.step()

    assert second.commarea[:4] == struct.pack(">i", 29)  # DFHRESP(ENDDATA)
    assert second.commarea[4:12] == "UNTOUCHD".encode("cp037")
    assert region.done is True


COBOL_STARTED_NO_RETRIEVE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NORTRV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA           PIC X(8)  VALUE 'NORETRVD'.
       PROCEDURE DIVISION.
           EXEC CICS RETURN TRANSID('SRTR') COMMAREA(WS-CA) END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_start_data_nobody_retrieved_does_not_reach_the_next_task(cobol_parser):
    """S3's stale-data rule end to end: the started task ends without RETRIEVEing,
    so its data is discarded — the next-transid task, entered from the terminal
    and started by nobody, must see ENDDATA and an untouched INTO area."""
    import struct

    context_holder: list = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    transid_map = {"SRTA": "STARTA", "SRTB": "NORTRV", "SRTR": "RTVNONE"}
    spec, builtins = _spec_with_queue(
        context_holder, result_holder, start_queue, transid_map
    )
    program_cache = {
        "STARTA": compile_cics_program(COBOL_START_A.encode(), cobol_parser, spec),
        "NORTRV": compile_cics_program(
            COBOL_STARTED_NO_RETRIEVE.encode(), cobol_parser, spec
        ),
        "RTVNONE": compile_cics_program(
            COBOL_RETRIEVE_NO_DATA.encode(), cobol_parser, spec
        ),
    }

    region = CicsRegion(
        program_cache,
        transid_map,
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        region_termid="T001",
        builtins=builtins,
    )

    first = region.start("SRTA", input_event=InputEvent())
    assert first.commarea == "RANAFTER".encode("cp037")
    assert region.transid == "SRTB"

    second = region.step()
    assert second.kind == DispatchKind.RETURN_TRANSID
    assert region.transid == "SRTR"

    third = region.step(input_event=InputEvent())

    assert third.commarea[:4] == struct.pack(">i", 29)  # DFHRESP(ENDDATA)
    assert third.commarea[4:12] == "UNTOUCHD".encode("cp037")
