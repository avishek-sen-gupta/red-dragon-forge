"""A packaged program declares the files of every program it links."""

from pathlib import Path

import pytest
from tests.covers import NotLanguageFeature, covers
from tests.package_build import FIXTURE_CBL, compiled, package

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


@pytest.mark.xfail(
    reason="a package cannot link a callee named only by CALL identifier"
    " (red-dragon-forge-8urg)",
    strict=True,
)
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_linked_subprograms_files_are_declared_by_the_step(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "LINKER.cbl").write_text(_CALLER)
    (src / "COPYUP.cbl").write_text((FIXTURE_CBL / "COPYUP.cbl").read_text())

    linker = compiled(package(tmp_path / "package", ("LINKER",), src), "LINKER")

    assert sorted(f.entry.assign_to for f in linker.files) == ["INDD", "OUTDD"]
