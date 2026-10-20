"""Integration: EXEC CICS LINK passes COMMAREA to target program and writes back.

Two programs are compiled:
  MUTATOR — modifies DFHCOMMAREA in-place (MOVE 'DONE' TO DFHCOMMAREA) then
            EXEC CICS RETURN.
  WRAPPER — declares WS-CA PIC X(4) VALUE 'INIT', LINKs to MUTATOR with
            COMMAREA(WS-CA), then EXEC CICS RETURN TRANSID('CC01').

The test verifies that after region.step() the WRAPPER's commarea carries 'DONE',
proving that the modified COMMAREA flowed back from MUTATOR into WS-CA.
"""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program, run_carddemo_region
from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.interval import StartQueue
from cics.dispatcher import CicsRegion, InputEvent
from cics.types import CicsContext, DispatchKind
from interpreter.cobol.features import CobolFeature
from tests.covers import covers
from tests.integration.cics.channel_drain import drain
from tests.integration.cobol_helpers import bridge_jar

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"

_DFHENTER = "\x7d"


@pytest.fixture(autouse=True)
def _require_bridge_jar(bridge_jar):
    """Fail loudly if PROLEAP_BRIDGE_JAR is not set."""


@pytest.fixture
def cobol_parser(bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.copybook_search import CopybookSearch
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    return ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybooks=CopybookSearch(dirs=(_CICS_COPYBOOKS,)),
    )


_MUTATOR_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MUTATOR.
       DATA DIVISION.
       LINKAGE SECTION.
       01 DFHCOMMAREA PIC X(4).
       PROCEDURE DIVISION.
           MOVE 'DONE' TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""

_WRAPPER_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WRAPPER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CA PIC X(4) VALUE 'INIT'.
       01 WS-RESP PIC S9(8) COMP VALUE 0.
       PROCEDURE DIVISION.
           EXEC CICS LINK PROGRAM('MUTATOR')
               COMMAREA(WS-CA) LENGTH(LENGTH OF WS-CA)
               RESP(WS-RESP)
           END-EXEC.
           EXEC CICS RETURN TRANSID('CC01') COMMAREA(WS-CA) END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_link_commarea_written_back(cobol_parser):
    """MUTATOR writes 'DONE' into DFHCOMMAREA; WRAPPER sees it in WS-CA."""
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    context_holder = [None]
    result_holder: list = [None]

    # program_cache is built first so the strategy can close over it.
    program_cache: dict = {}

    start_queue = StartQueue()
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        start_queue=start_queue,
        result_holder=result_holder,
        screen_queue=screen_q,
        input_queue=input_q,
        program_cache=program_cache,
    )
    spec = build_cics_spec()

    mutator = compile_cics_program(_MUTATOR_SRC.encode(), cobol_parser, spec)
    wrapper = compile_cics_program(_WRAPPER_SRC.encode(), cobol_parser, spec)

    program_cache["MUTATOR"] = mutator
    program_cache["WRAPPER"] = wrapper

    region = CicsRegion(
        program_cache,
        {"WR00": "WRAPPER"},
        screen_q,
        input_q,
        context_holder=context_holder,
        start_queue=start_queue,
        result_holder=result_holder,
        builtins=runtime.builtins,
    )

    result = region.start(
        "WR00",
        commarea=b"\x00" * 4,
        input_event=InputEvent(eibaid=_DFHENTER),
    )

    assert result.kind == DispatchKind.RETURN_TRANSID
    assert (result.transid or "").strip() == "CC01"
    ca = result.commarea or b""
    assert (
        ca[:4].decode("cp037", errors="replace").strip() == "DONE"
    ), f"expected 'DONE' in commarea, got {ca[:4]!r}"


_SHOWER_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SHOWER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 LNKMAP.
          05 RESULTO PIC X(4).
       01 WS-CA PIC X(4) VALUE 'INIT'.
       PROCEDURE DIVISION.
           EXEC CICS LINK PROGRAM('MUTATOR')
               COMMAREA(WS-CA) LENGTH(LENGTH OF WS-CA)
           END-EXEC.
           MOVE WS-CA TO RESULTO.
           EXEC CICS SEND MAP('LNKMAP') FROM(LNKMAP) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_link_between_programs_of_a_bootstrapped_region_reaches_the_callee(
    cobol_parser,
):
    """run_carddemo_region compiles every program the region names; a LINK from
    one to another must find the callee in the same cache the dispatcher runs
    from, not in an empty one of its own."""
    screen_q: queue.Queue = queue.Queue()

    result = run_carddemo_region(
        program_sources={
            "SHOWER": _SHOWER_SRC.encode(),
            "MUTATOR": _MUTATOR_SRC.encode(),
        },
        parser=cobol_parser,
        entry_transid="SH00",
        screen_queue=screen_q,
        input_queue=queue.Queue(),
        transid_to_program={"SH00": "SHOWER", "MU00": "MUTATOR"},
    )

    assert result.kind == DispatchKind.RETURN
    assert [(s["map"], s["fields"].get("RESULT")) for s in drain(screen_q)] == [
        ("LNKMAP", "DONE")
    ]


_SENDER_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SENDER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PAD PIC X(12) VALUE 'PADPADPADPAD'.
       01 SNDMAP.
          05 RESULTO PIC X(4).
       LINKAGE SECTION.
       01 DFHCOMMAREA PIC X(4).
       PROCEDURE DIVISION.
           MOVE 'CALL' TO RESULTO.
           EXEC CICS SEND MAP('SNDMAP') FROM(SNDMAP) END-EXEC.
           MOVE 'DONE' TO DFHCOMMAREA.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""

_CALLER_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 LNKMAP.
          05 RESULTO PIC X(4).
       01 WS-CA PIC X(4) VALUE 'INIT'.
       PROCEDURE DIVISION.
           EXEC CICS LINK PROGRAM('SENDER')
               COMMAREA(WS-CA) LENGTH(LENGTH OF WS-CA)
           END-EXEC.
           MOVE WS-CA TO RESULTO.
           EXEC CICS SEND MAP('LNKMAP') FROM(LNKMAP) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_a_linked_program_reads_its_own_fields_at_its_own_offsets(cobol_parser):
    """The LINKed program's RESULTO sits after a 12-byte pad, the caller's at
    offset 0; the callee's SEND MAP shows what the callee wrote there."""
    screen_q: queue.Queue = queue.Queue()

    result = run_carddemo_region(
        program_sources={
            "CALLER": _CALLER_SRC.encode(),
            "SENDER": _SENDER_SRC.encode(),
        },
        parser=cobol_parser,
        entry_transid="CA00",
        screen_queue=screen_q,
        input_queue=queue.Queue(),
        transid_to_program={"CA00": "CALLER", "SE00": "SENDER"},
    )

    assert result.kind == DispatchKind.RETURN
    assert [(s["map"], s["fields"].get("RESULT")) for s in drain(screen_q)] == [
        ("SNDMAP", "CALL"),
        ("LNKMAP", "DONE"),
    ]


_ABENDER_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ABENDER.
       PROCEDURE DIVISION.
           EXEC CICS ABEND ABCODE('LNK1') END-EXEC.
"""


def _linking_caller(handle_abend: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LCALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AFTER PIC X(8) VALUE 'AFTERLNK'.
       01 WS-EXIT  PIC X(8) VALUE 'EXIT RAN'.
       PROCEDURE DIVISION.
{handle_abend}
           EXEC CICS LINK PROGRAM('ABENDER') END-EXEC.
           EXEC CICS SEND TEXT FROM(WS-AFTER) END-EXEC.
           EXEC CICS RETURN END-EXEC.
       CALLER-EXIT.
           EXEC CICS SEND TEXT FROM(WS-EXIT) END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""


def _run_linking_region(caller_src: str, cobol_parser) -> tuple:
    screen_q: queue.Queue = queue.Queue()
    rollbacks: list[str] = []
    result = run_carddemo_region(
        program_sources={
            "LCALLER": caller_src.encode(),
            "ABENDER": _ABENDER_SRC.encode(),
        },
        parser=cobol_parser,
        entry_transid="LC00",
        screen_queue=screen_q,
        input_queue=queue.Queue(),
        transid_to_program={"LC00": "LCALLER", "AB00": "ABENDER"},
        on_abend=lambda: rollbacks.append("rolled back"),
    )
    return result, drain(screen_q), rollbacks


@covers(CobolFeature.EXEC_CICS)
def test_an_abend_in_a_linked_program_abends_a_caller_without_an_exit(
    cobol_parser,
):
    """With no exit at either level the task abends with the LINKed program's
    code, the caller does not run on past the LINK, and backout runs once."""
    result, screens, rollbacks = _run_linking_region(_linking_caller(""), cobol_parser)

    assert (result.kind, result.abcode, screens, rollbacks) == (
        DispatchKind.ABEND,
        "LNK1",
        [],
        ["rolled back"],
    )


@covers(CobolFeature.EXEC_CICS)
def test_an_abend_in_a_linked_program_reaches_the_callers_exit(cobol_parser):
    """CICS searches for an exit from the abending program's level upward: the
    caller's HANDLE ABEND exit handles the LINKed program's abend, so the task
    ends normally and no backout runs."""
    result, screens, rollbacks = _run_linking_region(
        _linking_caller(
            "           EXEC CICS HANDLE ABEND LABEL(CALLER-EXIT) END-EXEC."
        ),
        cobol_parser,
    )

    assert (result.kind, screens, rollbacks) == (
        DispatchKind.RETURN,
        [{"type": "text", "text": "EXIT RAN"}],
        [],
    )


def _unknown_link(resp: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LCALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RESP       PIC S9(8) COMP.
       01 WS-RESP-SHOWN PIC X(8).
       PROCEDURE DIVISION.
           EXEC CICS LINK PROGRAM('NOSUCH') {resp} END-EXEC.
           MOVE WS-RESP TO WS-RESP-SHOWN.
           EXEC CICS SEND TEXT FROM(WS-RESP-SHOWN) END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
@pytest.mark.parametrize(
    ("resp", "expected"),
    [
        (
            "RESP(WS-RESP)",
            (DispatchKind.RETURN, None, [{"type": "text", "text": "00000027"}], []),
        ),
        ("", (DispatchKind.ABEND, "AEIZ", [], ["rolled back"])),
    ],
    ids=["under-resp", "unhandled"],
)
def test_a_link_to_an_unknown_program_raises_pgmiderr(cobol_parser, resp, expected):
    """LINK to a program the region lacks raises PGMIDERR: RESP sees 27 and
    control continues; with nothing handling it the task abends."""
    result, screens, rollbacks = _run_linking_region(_unknown_link(resp), cobol_parser)

    assert (result.kind, result.abcode, screens, rollbacks) == expected
