"""Integration: EXEC CICS interval control — START and RETRIEVE scenarios.

Each scenario drives complete COBOL through the real compile + region path and
asserts DECODED DATA, never that a branch ran (see
docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md).
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
from cics.dispatcher import CicsRegion, InputEvent, run_cics
from cics.interval import RejectReason, StartQueue, StartRequest
from cics.preprocessor import apply_cics_prepass
from cics.statements import CicsDialectParser
from cics.strategy import CicsLoweringStrategy
from cics.types import CicsContext, DispatchKind
from cobol_asg.cobol_parser import ProLeapCobolParser
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
    return ProLeapCobolParser(runner, bridge_jar, copybook_dirs=[_CICS_COPYBOOKS])


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
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    program = compile_cics_program(COBOL_EIBTRMID.encode(), cobol_parser, spec)

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
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
    return build_cics_spec(
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        transid_to_program=transid_map,
        region_termid="T001",
    )


@covers(CobolFeature.EXEC_CICS)
def test_start_queues_the_request_and_the_program_keeps_running(cobol_parser):
    """S1 assertions 1 and 3, without a region: the request lands AND the
    statement after the START executes."""
    context_holder = [
        CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001")
    ]
    result_holder: list = [None]
    start_queue = StartQueue()
    spec = _spec_with_queue(
        context_holder, result_holder, start_queue, {"SRTB": "STARTB"}
    )
    program = compile_cics_program(COBOL_START_A.encode(), cobol_parser, spec)

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
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
    context_holder = [
        CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001")
    ]
    strategy = CicsLoweringStrategy(
        context_holder=context_holder,
        result_holder=[None],
        start_queue=StartQueue(),
        transid_to_program={"SRTB": "STARTB"},
        region_termid="T001",
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

    # COBOL_START_A has exactly one EXEC CICS statement that ends a task — the
    # trailing RETURN — so the whole program must emit exactly one Return_. A
    # second one anywhere would mean START itself ended the task, which is the
    # regression this test exists to catch (a windowed slice after the START
    # call would miss a Return_ emitted further down as the program grows).
    return_instructions = [i for i in instructions if isinstance(i, Return_)]
    assert len(return_instructions) == 1, (
        f"expected exactly one Return_ (from the trailing RETURN), got "
        f"{len(return_instructions)} — START must not emit its own"
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
    spec = _spec_with_queue(context_holder, result_holder, start_queue, {})
    program = compile_cics_program(COBOL_RETRIEVE_NO_DATA.encode(), cobol_parser, spec)

    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
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
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
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
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
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
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
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
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
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
    spec = _spec_with_queue(context_holder, result_holder, start_queue, transid_map)
    program = compile_cics_program(source.encode(), cobol_parser, spec)
    return run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        context_holder=context_holder,
        result_holder=result_holder,
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
