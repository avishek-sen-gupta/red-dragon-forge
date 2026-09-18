"""Integration (JAR-gated): a REAL two-turn CICS region run.

This is the CICS epic's fitness function. It drives a real pseudo-conversational
sign-on -> menu flow through COMPILED-AND-EXECUTED COBOL (no stubbed run_fn):

  pre-pass -> ProLeap -> CICS lowering -> VM -> builtins -> screen / COMMAREA.

  Turn 1: CC00 / SGNPGM  -- MOVE a value into a symbolic output field, SEND MAP
          SGNMAP, RETURN TRANSID('CM00') COMMAREA(WS-CA).
  Turn 2: CM00 / MENUPGM -- read DFHCOMMAREA into a symbolic output field,
          SEND MAP MENMAP, RETURN (terminate).

The dispatcher carries the COMMAREA from SGNPGM into MENUPGM; the second screen
reflects bytes that originated in the first program's COMMAREA, proving the whole
stack works end to end.
"""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature
from cics.bootstrap import run_carddemo_region
from cics.dispatcher import InputEvent
from cics.types import DispatchKind
from tests.integration.cics.channel_drain import drain
from tests.covers import covers
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


# Sign-on program: MOVE 'WELCOME!' into the SGNMAP symbolic output field MSGO,
# carry the same value in the COMMAREA, then RETURN TRANSID('CM00').
SGNPGM_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SGNPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 SGNMAP.
          05 MSGO PIC X(8).
       01 WS-CA.
          05 WS-CA-MSG PIC X(8).
       PROCEDURE DIVISION.
           MOVE 'WELCOME!' TO MSGO.
           MOVE 'WELCOME!' TO WS-CA-MSG.
           EXEC CICS SEND MAP('SGNMAP') FROM(SGNMAP) END-EXEC.
           EXEC CICS RETURN TRANSID('CM00') COMMAREA(WS-CA) END-EXEC.
           STOP RUN.
"""

# Menu program: read DFHCOMMAREA into the MENMAP symbolic output field MENMSGO,
# SEND MAP, RETURN (terminate). The carried COMMAREA value becomes visible on
# the menu screen.
MENUPGM_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MENUPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 MENMAP.
          05 MENMSGO PIC X(8).
       LINKAGE SECTION.
       01 DFHCOMMAREA.
          05 DFH-CA-MSG PIC X(8).
       PROCEDURE DIVISION.
           MOVE DFH-CA-MSG TO MENMSGO.
           EXEC CICS SEND MAP('MENMAP') FROM(MENMAP) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_two_turn_region_real_execution(cobol_parser):
    """Real compiled sign-on -> menu flow: two screens + COMMAREA carry-through."""
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    # Unblocks the RETURN TRANSID turn transition (CC00 -> CM00).
    input_q.put(InputEvent(eibaid="\x7d", fields={}))

    program_sources = {
        "SGNPGM": SGNPGM_SRC.encode(),
        "MENUPGM": MENUPGM_SRC.encode(),
    }

    result = run_carddemo_region(
        transid_to_program={"CC00": "SGNPGM", "CM00": "MENUPGM"},
        program_sources=program_sources,
        parser=cobol_parser,
        entry_transid="CC00",
        screen_queue=screen_q,
        input_queue=input_q,
    )

    # Loop terminated on MENUPGM's RETURN.
    assert result.kind == DispatchKind.RETURN

    screens = drain(screen_q)

    # Two screens, in order: sign-on then menu.
    assert [s["map"] for s in screens] == ["SGNMAP", "MENMAP"]

    # Screen 1 reflects the value SGNPGM MOVEd into the symbolic output field.
    assert screens[0]["fields"].get("MSG") == "WELCOME!"

    # Screen 2 reflects the COMMAREA value carried from SGNPGM into MENUPGM.
    assert screens[1]["fields"].get("MENMSG") == "WELCOME!"


# Data-name map program (the standard CardDemo idiom, e.g. MAP(CCARD-NEXT-MAP)):
# the map NAME is held in a WS field, set at runtime, then SEND MAP(WS-MAPNM).
# Before the structural fix this rendered nothing because WS-MAPNM (the field
# NAME) was passed to the loader instead of its runtime VALUE 'MYMAP'.
DATANAME_PGM_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DNPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MAPNM PIC X(7).
       01 MYMAP.
          05 GREETO PIC X(8).
       PROCEDURE DIVISION.
           MOVE 'MYMAP' TO WS-MAPNM.
           MOVE 'HELLO!' TO GREETO.
           EXEC CICS SEND MAP(WS-MAPNM) FROM(MYMAP) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_send_map_data_name_resolves_runtime_value(cobol_parser):
    """SEND MAP(WS-MAPNM) sends the runtime VALUE 'MYMAP', not the field name (g5gx)."""
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()

    result = run_carddemo_region(
        transid_to_program={"CC00": "DNPGM"},
        program_sources={"DNPGM": DATANAME_PGM_SRC.encode()},
        parser=cobol_parser,
        entry_transid="CC00",
        screen_queue=screen_q,
        input_queue=input_q,
    )

    assert result.kind == DispatchKind.RETURN

    screens = drain(screen_q)

    assert len(screens) == 1
    # The map name is the DECODED field value 'MYMAP' (not 'WS-MAPNM').
    assert screens[0]["map"] == "MYMAP"
    assert screens[0]["fields"].get("GREET") == "HELLO!"


# Two-turn program pair for v2om: turn 1 SENDs a prompt and RETURN TRANSIDs;
# turn 2 checks EIBAID (the standard CardDemo idiom — branch on the attention
# key BEFORE pulling field values) and calls RECEIVE MAP for the typed field,
# in the SAME invocation. Both must come from the SAME terminal input event.
# Before the fix, _run_dispatcher_with_runner's own input_queue.get() (reading
# eibaid for the next turn) drained that event before RECEIVE MAP could see it.
ASKPGM_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ASKPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 ASKMAP.
          05 PROMPTO PIC X(8).
       PROCEDURE DIVISION.
           MOVE 'ENTER ID' TO PROMPTO.
           EXEC CICS SEND MAP('ASKMAP') FROM(ASKMAP) END-EXEC.
           EXEC CICS RETURN TRANSID('CC02') END-EXEC.
           STOP RUN.
"""

RESUMEPGM_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RESUMEPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 RESMAP.
          05 UNAMEI PIC X(8).
          05 AIDFLGO PIC X(8).
          05 UNAMEO PIC X(8).
       COPY DFHAID.
       PROCEDURE DIVISION.
           IF EIBAID = DFHPF3
               MOVE 'PF3SEEN!' TO AIDFLGO
           ELSE
               MOVE 'OTHERAID' TO AIDFLGO
           END-IF.
           EXEC CICS RECEIVE MAP('RESMAP') INTO(RESMAP) END-EXEC.
           MOVE UNAMEI TO UNAMEO.
           EXEC CICS SEND MAP('RESMAP') FROM(RESMAP) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_return_transid_then_receive_map_both_see_the_same_event(cobol_parser):
    """The resumed turn's EIBAID branch AND its RECEIVE MAP field both come from
    the one terminal input event that unblocked RETURN TRANSID (v2om)."""
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    # Unblocks the RETURN TRANSID turn transition (CC00 -> CC02): PF3, with the
    # field RECEIVE MAP must also pick up on the SAME turn.
    input_q.put(InputEvent(eibaid="\xf3", fields={"UNAME": "ALICE"}))

    program_sources = {
        "ASKPGM": ASKPGM_SRC.encode(),
        "RESUMEPGM": RESUMEPGM_SRC.encode(),
    }

    result = run_carddemo_region(
        transid_to_program={"CC00": "ASKPGM", "CC02": "RESUMEPGM"},
        program_sources=program_sources,
        parser=cobol_parser,
        entry_transid="CC00",
        screen_queue=screen_q,
        input_queue=input_q,
    )

    assert result.kind == DispatchKind.RETURN

    screens = drain(screen_q)
    assert [s["map"] for s in screens] == ["ASKMAP", "RESMAP"]

    resume_fields = screens[1]["fields"]
    # EIBAID (PF3) was seen by the branch BEFORE RECEIVE MAP ran...
    assert resume_fields.get("AIDFLG") == "PF3SEEN!"
    # ...AND RECEIVE MAP still got the field value from that same event.
    assert resume_fields.get("UNAME") == "ALICE"


# WRITEQ TD RESP writeback proof (cicada-y6l): WS-RESP-CD starts "poisoned" at
# a sentinel that is NOT a real CICS response code (999). Only a genuine
# RESP writeback can bring it back to 0 — a naive "assert it's 0" test can't
# distinguish "fixed" from "field was already 0 and nothing touched it",
# since 0 is also DFHRESP(NORMAL). The MOVE to a DISPLAY field before SEND
# MAP is required because WS-RESP-CD is COMP (binary) — not printable via a
# symbolic map directly; real COBOL programs always de-edit COMP fields to
# DISPLAY before showing them on screen, same as this test does.
TDRESPGM_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TDRESPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TDRMAP.
          05 RESPO PIC 9(9).
       01 WS-DATA PIC X(8) VALUE 'HELLOTD!'.
       01 WS-RESP-CD PIC S9(09) COMP VALUE 999.
       PROCEDURE DIVISION.
           EXEC CICS WRITEQ TD QUEUE('TESTQ') FROM(WS-DATA)
                     RESP(WS-RESP-CD) END-EXEC.
           MOVE WS-RESP-CD TO RESPO.
           EXEC CICS SEND MAP('TDRMAP') FROM(TDRMAP) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_writeq_td_writes_back_resp(cobol_parser):
    """WRITEQ TD's RESP(WS-RESP-CD) is genuinely written, not silently
    dropped: a poisoned sentinel (999) becomes 0 (DFHRESP(NORMAL)) after the
    call — proving the writeback executed rather than the field already
    being 0 (cicada-y6l)."""
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()

    result = run_carddemo_region(
        transid_to_program={"CC00": "TDRESPGM"},
        program_sources={"TDRESPGM": TDRESPGM_SRC.encode()},
        parser=cobol_parser,
        entry_transid="CC00",
        screen_queue=screen_q,
        input_queue=input_q,
    )

    assert result.kind == DispatchKind.RETURN

    screens = drain(screen_q)
    assert len(screens) == 1
    assert screens[0]["map"] == "TDRMAP"
    assert screens[0]["fields"].get("RESP") == "000000000", (
        f"expected WS-RESP-CD written back to 0 (DFHRESP(NORMAL)), "
        f"got screen fields: {screens[0]['fields']!r}"
    )


# SEND TEXT FROM(data-name) previously ignored FROM entirely and rendered a
# blank screen (only a literal TEXT('...') worked). SYNCPOINT is exercised on
# the same path to prove it no longer abends the task.
SENDTEXT_PGM_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. STXTPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MESSAGE PIC X(20) VALUE 'HELLO FROM CARDDEMO'.
       PROCEDURE DIVISION.
           EXEC CICS SYNCPOINT END-EXEC.
           EXEC CICS SEND TEXT FROM(WS-MESSAGE) END-EXEC.
           EXEC CICS RETURN END-EXEC.
           STOP RUN.
"""


@covers(CobolFeature.EXEC_CICS)
def test_send_text_from_puts_the_fields_value_on_the_screen_channel(cobol_parser):
    """SEND TEXT FROM(WS-MESSAGE) must carry WS-MESSAGE's runtime text onto the
    screen channel, and the preceding SYNCPOINT must not abend the task."""
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()

    result = run_carddemo_region(
        transid_to_program={"CC00": "STXTPGM"},
        program_sources={"STXTPGM": SENDTEXT_PGM_SRC.encode()},
        parser=cobol_parser,
        entry_transid="CC00",
        screen_queue=screen_q,
        input_queue=input_q,
    )

    assert result.kind == DispatchKind.RETURN

    screens = drain(screen_q)
    assert len(screens) == 1
    assert screens[0]["type"] == "text"
    # WS-MESSAGE is PIC X(20); its decoded value is space-padded to that width.
    assert screens[0]["text"].rstrip() == "HELLO FROM CARDDEMO"
