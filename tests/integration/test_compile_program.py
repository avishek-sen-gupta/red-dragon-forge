from __future__ import annotations

import os

import pytest

from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner

from red_dragon_forge.compile import compile_program
from red_dragon_forge.coprocessor import CoprocessorSpec


@pytest.fixture
def bridge_jar() -> str:
    return os.environ["PROLEAP_BRIDGE_JAR"]


_TRIVIAL_PROGRAM = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRIVIAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FIELD PIC X(10).
       PROCEDURE DIVISION.
           MOVE 'HELLO' TO WS-FIELD.
           STOP RUN.
"""


def test_every_specs_prepass_runs_before_any_make_strategy(bridge_jar):
    call_order = []

    def prepass_a(source: str) -> str:
        call_order.append("prepass_a")
        return source

    def prepass_b(source: str) -> str:
        call_order.append("prepass_b")
        return source

    def make_strategy_a():
        call_order.append("make_strategy_a")
        return _FakeStrategy()

    def make_strategy_b():
        call_order.append("make_strategy_b")
        return _FakeStrategy()

    specs = [
        CoprocessorSpec(name="a", make_strategy=make_strategy_a, source_prepass=prepass_a),
        CoprocessorSpec(name="b", make_strategy=make_strategy_b, source_prepass=prepass_b),
    ]
    parser = ProLeapCobolParser(RealSubprocessRunner(), bridge_jar)

    compile_program(_TRIVIAL_PROGRAM, parser, specs)

    assert call_order == [
        "prepass_a",
        "prepass_b",
        "make_strategy_a",
        "make_strategy_b",
    ]


class _FakeStrategy:
    """A minimal RedDragonExtensionLoweringStrategy that handles nothing —
    proves compile_program's plumbing without needing real CICS/SQL lowering."""

    def handles(self, stmt) -> bool:
        return False

    def preprocess_program_dict(self, data: dict) -> dict:
        return data

    def on_procedure_entry(self, ctx, materialised) -> None:
        pass

    def lower(self, ctx, stmt, materialised) -> None:
        pass
