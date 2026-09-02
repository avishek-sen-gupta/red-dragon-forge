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
from cics.dispatcher import run_cics
from cics.types import CicsContext, DispatchKind
from cobol_asg.cobol_parser import ProLeapCobolParser
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
