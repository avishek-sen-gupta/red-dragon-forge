"""Parity: the files read from the linked program's Data equal those read from its ASTs."""

from pathlib import Path

import pytest
from jackal.file_definitions import program_files_of
from jackal.program_compiler import ProgramCompiler
from tests.covers import NotLanguageFeature, covers

CBL = Path(__file__).parent / "fixtures" / "cbl"


@pytest.fixture(autouse=True)
def _require_bridge(bridge_jar):
    """Enforce PROLEAP_BRIDGE_JAR."""


@pytest.mark.parametrize("source", sorted(CBL.glob("*.cbl")), ids=lambda p: p.stem)
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_files_from_data_equal_files_from_asts(bridge_jar, source):
    compiled = ProgramCompiler(bridge_jar, (), (CBL,), ()).compiled(source.read_text())

    assert program_files_of(compiled.linked) == compiled.files
