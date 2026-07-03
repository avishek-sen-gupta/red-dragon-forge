# tests/integration/test_cics_adapter.py
from __future__ import annotations

import queue
from pathlib import Path

import cics
from cics.dispatcher import run_cics
from cics.types import CicsContext, DispatchKind

from red_dragon_forge.adapters.cics import build_cics_spec
from red_dragon_forge.compile import compile_program

# The prepass injects `COPY DFHEIBLK.` into WORKING-STORAGE; ProLeap resolves
# that copybook against this directory, same as every Cicada CICS integration
# test (see e.g. vendor/cicada/tests/integration/cics/test_link.py).
_CICS_COPYBOOKS = Path(cics.__file__).parent / "copybooks"

_CICS_ONLY_PROGRAM = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSONLY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FIELD PIC X(10).
       PROCEDURE DIVISION.
           MOVE 'HELLO' TO WS-FIELD.
           EXEC CICS RETURN
           END-EXEC.
"""


def test_cics_only_spec_compiles_and_returns(bridge_jar):
    from interpreter.cobol.cobol_parser import ProLeapCobolParser
    from interpreter.cobol.subprocess_runner import RealSubprocessRunner

    context_holder = [None]
    result_holder = [None]
    spec = build_cics_spec(context_holder=context_holder, result_holder=result_holder)
    parser = ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[_CICS_COPYBOOKS]
    )

    _frontend, linked = compile_program(_CICS_ONLY_PROGRAM, parser, [spec])

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    result = run_cics(
        linked,
        CicsContext(transid="CICO", commarea=b"", eibaid="\x7d"),
        screen_q,
        input_q,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=10_000,
    )

    assert result.kind == DispatchKind.RETURN
