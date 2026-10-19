"""Integration: an EXEC CICS verb this runtime does not implement is loud.

Dropping the statement and lowering nothing let a program run on as though the
command had succeeded, so a run could skip its downstream flow, end on a normal
RETURN and look clean (forge-p9t). The corpus carries unimplemented verbs on
abend and error paths a healthy run never reaches, so refusing to compile would
block whole programs over code that never executes; the statement lowers to an
abend instead, and the compile collects the verbs it dropped.
"""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.dispatcher import run_cics
from tests.integration.cobol_helpers import main_entry
from cics.types import CicsContext, DispatchKind
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature

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


COBOL_REACHES_UNSUPPORTED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNSUPA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA  PIC X(8) VALUE 'RANAFTER'.
       PROCEDURE DIVISION.
           EXEC CICS ENQ END-EXEC.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""


COBOL_NEVER_REACHES_UNSUPPORTED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNSUPB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA  PIC X(8) VALUE 'CLEANRUN'.
       PROCEDURE DIVISION.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
       PARA-NEVER-RUN.
           EXEC CICS ENQ END-EXEC.
"""


def _run(source: bytes, cobol_parser, unsupported: set):
    context_holder = [CicsContext(transid="UNS1", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        result_holder=result_holder,
    )
    spec = build_cics_spec(unsupported_verbs=unsupported)
    program = compile_cics_program(source, cobol_parser, spec)
    return run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=runtime.builtins,
    )


@covers(CobolFeature.EXEC_CICS)
def test_executing_an_unsupported_verb_abends(cobol_parser):
    """The RETURN after the unsupported statement must not run: its commarea is
    the evidence. Reaching it would mean the program carried on as though
    ENQ had succeeded."""
    collected: set = set()
    result = _run(COBOL_REACHES_UNSUPPORTED.encode(), cobol_parser, collected)

    assert result.kind == DispatchKind.ABEND
    assert result.abcode == "UNSP"
    assert result.commarea != "RANAFTER".encode("cp037")


@covers(CobolFeature.EXEC_CICS)
def test_an_unsupported_verb_on_an_unreached_path_does_not_abend(cobol_parser):
    """Compiling is not refused. PARA-NEVER-RUN falls after the RETURN, so the
    program completes normally -- this is why lowering does not raise: the
    corpus keeps unimplemented verbs on abend paths a healthy run never
    touches."""
    collected: set = set()
    result = _run(COBOL_NEVER_REACHES_UNSUPPORTED.encode(), cobol_parser, collected)

    assert result.kind == DispatchKind.RETURN
    assert result.commarea == "CLEANRUN".encode("cp037")


@covers(CobolFeature.EXEC_CICS)
def test_the_compile_reports_which_verbs_it_dropped(cobol_parser):
    """The set is the assertable channel a log line could never be: a harness
    can fail on it without scraping a shared logger. It is populated whether or
    not the statement ever executes, because it describes the compile."""
    collected: set = set()
    _run(COBOL_NEVER_REACHES_UNSUPPORTED.encode(), cobol_parser, collected)

    assert collected == {"ENQ"}


@covers(CobolFeature.EXEC_CICS)
def test_a_program_using_only_supported_verbs_reports_nothing(cobol_parser):
    """Guards the discrimination of the test above: an empty set must mean
    "nothing was dropped", not "the collector was never wired up"."""
    collected: set = set()
    source = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNSUPC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CA  PIC X(8) VALUE 'ALLGOOD0'.
       PROCEDURE DIVISION.
           EXEC CICS RETURN COMMAREA(WS-CA) END-EXEC.
"""
    result = _run(source, cobol_parser, collected)

    assert collected == set()
    assert result.commarea == "ALLGOOD0".encode("cp037")
