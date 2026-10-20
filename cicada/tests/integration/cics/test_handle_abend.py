"""Integration: EXEC CICS HANDLE ABEND LABEL and CANCEL drive the abend exit,
and an XCTL to a program the region lacks raises PGMIDERR in the program."""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.coprocessor import build_cics_spec
from cics.dispatcher import run_cics
from cics.runtime import install_cics_runtime
from cics.types import CicsContext, DispatchKind, DispatchResult
from cics.vsam.engine import VsamEngine
from cics.vsam.file_table import cics_files
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature

from tests.covers import covers
from tests.integration.cics.channel_drain import drain
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401
from tests.integration.cobol_helpers import main_entry
from tests.vsam_system import SeedCluster, build_test_system

_CICS_COPYBOOKS = Path(__file__).resolve().parents[3] / "cics" / "copybooks"


@pytest.fixture
def cobol_parser(bridge_jar):  # noqa: F811
    return ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybooks=CopybookSearch(dirs=(_CICS_COPYBOOKS,)),
    )


def _run(
    source: str, parser: ProLeapCobolParser, tmp_path: Path
) -> tuple[DispatchResult, list[dict[str, str]], list[str]]:
    engine = VsamEngine(
        cics_files(*build_test_system(tmp_path, (SeedCluster("ACCTFILE", 80, 11, ()),)))
    )
    context_holder = [CicsContext(transid="HABN", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    rollbacks: list[str] = []
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        result_holder=result_holder,
        vsam_engine=engine,
        screen_queue=screen_q,
        input_queue=input_q,
        on_abend=lambda: rollbacks.append("rolled back"),
    )
    program = compile_cics_program(source.encode(), parser, build_cics_spec())
    result = run_cics(
        program,
        context_holder[0],
        screen_q,
        input_q,
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=runtime.builtins,
    )
    return result, drain(screen_q), rollbacks


def _program(raise_abend: str, exit_body: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HABNPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC        PIC X(80).
       01  WS-KEY        PIC X(11) VALUE '99999999999'.
       01  WS-MSG        PIC X(8) VALUE 'EXIT RAN'.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE ABEND LABEL(ABEND-ROUTINE) END-EXEC.
{raise_abend}
           EXEC CICS RETURN END-EXEC.
       ABEND-ROUTINE.
           EXEC CICS SEND TEXT FROM(WS-MSG) END-EXEC.
{exit_body}
"""


_ABEND_VERB = "           EXEC CICS ABEND ABCODE('AAAA') END-EXEC."
_UNHANDLED_CONDITION = """\
           EXEC CICS READ FILE('ACCTFILE') INTO(WS-REC) RIDFLD(WS-KEY)
           END-EXEC."""
_UNSUPPORTED_VERB = "           EXEC CICS READQ TS QUEUE('Q1') INTO(WS-REC) END-EXEC."
_XCTL_UNKNOWN = "           EXEC CICS XCTL PROGRAM('NOSUCH') END-EXEC."
_RETURN = "           EXEC CICS RETURN END-EXEC."
_ABEND_9999 = "           EXEC CICS ABEND ABCODE('9999') END-EXEC."


@covers(CobolFeature.EXEC_CICS)
@pytest.mark.parametrize(
    "raise_abend",
    [_ABEND_VERB, _UNHANDLED_CONDITION, _UNSUPPORTED_VERB, _XCTL_UNKNOWN],
    ids=["abend-verb", "unhandled-condition", "unsupported-verb", "xctl-unknown"],
)
def test_an_abend_transfers_to_the_exit_and_a_handled_abend_is_not_backed_out(
    cobol_parser, tmp_path, raise_abend
):
    """Each abend the program itself raises transfers to the HANDLE ABEND LABEL
    paragraph. The exit RETURNs, so the task ends normally, and a handled abend
    does not invoke backout (IBM: Abnormal termination recovery)."""
    result, screens, rollbacks = _run(
        _program(raise_abend, _RETURN), cobol_parser, tmp_path
    )

    assert (result.kind, screens, rollbacks) == (
        DispatchKind.RETURN,
        [{"type": "text", "text": "EXIT RAN"}],
        [],
    )


@covers(CobolFeature.EXEC_CICS)
def test_the_exit_is_deactivated_on_entry_so_an_abend_in_it_ends_the_task(
    cobol_parser, tmp_path
):
    """CICS deactivates the exit upon entry to it. The exit's own ABEND therefore
    ends the task with that code instead of re-entering the exit, and backout
    runs once."""
    result, screens, rollbacks = _run(
        _program(_ABEND_VERB, _ABEND_9999), cobol_parser, tmp_path
    )

    assert (result.kind, result.abcode, screens, rollbacks) == (
        DispatchKind.ABEND,
        "9999",
        [{"type": "text", "text": "EXIT RAN"}],
        ["rolled back"],
    )


_HANDLE_ABEND_CANCEL = """\
           EXEC CICS HANDLE ABEND CANCEL END-EXEC.
           EXEC CICS ABEND ABCODE('1234') END-EXEC."""
_ABEND_CANCEL = "           EXEC CICS ABEND ABCODE('1234') CANCEL END-EXEC."


@covers(CobolFeature.EXEC_CICS)
@pytest.mark.parametrize(
    "raise_abend",
    [_HANDLE_ABEND_CANCEL, _ABEND_CANCEL],
    ids=["handle-abend-cancel", "abend-cancel"],
)
def test_a_cancelled_exit_never_runs(cobol_parser, tmp_path, raise_abend):
    """HANDLE ABEND CANCEL removes the exit, and ABEND CANCEL ignores it (IBM:
    "exits established by HANDLE ABEND commands are ignored"): the task abends
    with the program's code and the exit never runs."""
    result, screens, rollbacks = _run(
        _program(raise_abend, _RETURN), cobol_parser, tmp_path
    )

    assert (result.kind, result.abcode, screens, rollbacks) == (
        DispatchKind.ABEND,
        "1234",
        [],
        ["rolled back"],
    )


_XCTL_UNDER_RESP = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. XCTLRESP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP       PIC S9(8) COMP.
       01  WS-RESP-SHOWN PIC X(8).
       PROCEDURE DIVISION.
           EXEC CICS XCTL PROGRAM('NOSUCH') RESP(WS-RESP) END-EXEC.
           MOVE WS-RESP TO WS-RESP-SHOWN.
           EXEC CICS SEND TEXT FROM(WS-RESP-SHOWN) END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_an_xctl_to_an_unknown_program_reports_pgmiderr_inline_under_resp(
    cobol_parser, tmp_path
):
    """With RESP coded the program checks the outcome itself: control returns
    after the XCTL with RESP set to PGMIDERR (27), and nothing abends."""
    result, screens, rollbacks = _run(_XCTL_UNDER_RESP, cobol_parser, tmp_path)

    assert (result.kind, screens, rollbacks) == (
        DispatchKind.RETURN,
        [{"type": "text", "text": "00000027"}],
        [],
    )


_EXIT_SECTION = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HABNSEC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MSG        PIC X(8) VALUE 'EXIT RAN'.
       PROCEDURE DIVISION.
       MAIN-LOGIC SECTION.
           EXEC CICS HANDLE ABEND LABEL(ABEND-HANDLING) END-EXEC.
           EXEC CICS ABEND ABCODE('AAAA') END-EXEC.
           EXEC CICS RETURN END-EXEC.
       ABEND-HANDLING SECTION.
           EXEC CICS SEND TEXT FROM(WS-MSG) END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""


@covers(CobolFeature.EXEC_CICS)
def test_an_exit_may_name_a_section(cobol_parser, tmp_path):
    """LABEL may name a section as well as a paragraph; the abend transfers to
    the section."""
    result, screens, rollbacks = _run(_EXIT_SECTION, cobol_parser, tmp_path)

    assert (result.kind, screens, rollbacks) == (
        DispatchKind.RETURN,
        [{"type": "text", "text": "EXIT RAN"}],
        [],
    )
