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
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    return ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[_CICS_COPYBOOKS]
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
    spec = build_cics_spec(
        transid_to_program={},
        start_queue=start_queue,
        context_holder=context_holder,
        result_holder=result_holder,
        screen_queue=screen_q,
        input_queue=input_q,
        program_cache=program_cache,
    )

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
