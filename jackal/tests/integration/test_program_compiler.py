"""ProgramCompiler: the files a compiled step declares, across every program it links."""

from pathlib import Path

import pytest
from jackal.model import ProgramRef
from jackal.program_compiler import ProgramCompiler
from jackal.program_sources import CobolSource
from tests.covers import NotLanguageFeature, covers

CBL = Path(__file__).parent / "fixtures" / "cbl"

_CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LINKER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CALLEE PIC X(8) VALUE 'COPYUP'.
       PROCEDURE DIVISION.
           CALL WS-CALLEE.
           GOBACK.
"""


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_linked_subprograms_files_are_declared_by_the_step(bridge_jar):
    compiler = ProgramCompiler(
        bridge_jar,
        (),
        (),
        (),
        linked={ProgramRef("COPYUP"): CobolSource((CBL / "COPYUP.cbl").read_text())},
    )

    compiled = compiler.compiled(_CALLER)

    assert sorted(f.entry.assign_to for f in compiled.files) == ["INDD", "OUTDD"]
