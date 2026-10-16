"""A step declares the files of every program linked into its image, whichever way the caller names its callee."""

from pathlib import Path

import pytest
from tests.covers import NotLanguageFeature, covers
from tests.package_build import FIXTURE_CBL, compiled, package

_BY_IDENTIFIER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LINKER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CALLEE PIC X(8) VALUE 'COPYUP'.
       PROCEDURE DIVISION.
           CALL WS-CALLEE.
           GOBACK.
"""
_BY_LITERAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LINKER.
       PROCEDURE DIVISION.
           CALL 'COPYUP'.
           GOBACK.
"""


@pytest.mark.parametrize("caller", [_BY_IDENTIFIER, _BY_LITERAL])
@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_linked_subprograms_files_are_declared_by_the_step(
    tmp_path: Path, bridge_jar: str, caller: str
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "LINKER.cbl").write_text(caller)
    (src / "COPYUP.cbl").write_text((FIXTURE_CBL / "COPYUP.cbl").read_text())

    linker = compiled(
        package(tmp_path / "package", bridge_jar, ("LINKER", "COPYUP"), src), "LINKER"
    )

    assert sorted((f.program, f.entry.assign_to) for f in linker.files) == [
        ("COPYUP", "INDD"),
        ("COPYUP", "OUTDD"),
    ]
