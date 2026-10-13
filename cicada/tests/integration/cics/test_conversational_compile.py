"""Conversational and blocking compiles of one program keep separate files."""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from cics.coprocessor import build_cics_spec
from interpreter.cobol.features import CobolFeature
from interpreter.instructions import Suspend
from interpreter.project.cobol_compile import compile_cobol
from interpreter.project.types import LinkedProgram
from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"

_RECEIVER_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ASKER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ASKMAPI.
           05  FLD1L PIC S9(4) COMP.
           05  FLD1F PIC X.
           05  FLD1I PIC X(8).
       PROCEDURE DIVISION.
           EXEC CICS RECEIVE MAP('ASKMAP') INTO(ASKMAPI) END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""


@pytest.fixture
def cobol_parser(bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    return ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[_CICS_COPYBOOKS]
    )


def _compiled(cobol_parser, conversational: bool, work_dir: Path) -> LinkedProgram:
    spec = build_cics_spec(
        transid_to_program={},
        program_cache={},
        context_holder=[None],
        result_holder=[None],
        screen_queue=queue.Queue(),
        input_queue=queue.Queue(),
        conversational=conversational,
    )
    return compile_cobol(
        spec.source_prepass(_RECEIVER_SRC).encode(),
        parser=cobol_parser,
        extension_strategies=[spec.make_strategy()],
        dialect_parsers=[spec.dialect_parser],
        work_dir=work_dir,
    )


def _suspends(program: LinkedProgram) -> int:
    return sum(isinstance(inst, Suspend) for inst in program.merged_ir)


@covers(CobolFeature.EXEC_CICS)
def test_a_conversational_compile_does_not_reuse_the_blocking_files(
    cobol_parser, tmp_path
):
    blocking = _compiled(cobol_parser, False, tmp_path)
    conversational = _compiled(cobol_parser, True, tmp_path)

    assert (_suspends(blocking), _suspends(conversational)) == (0, 1)
