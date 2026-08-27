"""The COPY/CALL scanner's source positions.

A COPY's line number is what makes a missing copybook actionable: 315 names
missing across 1766 programs is a number, ``member X line 412`` is somewhere to
look. The scanner is the one place that knows it, and it has to be exact —
comment lines are stripped before the grammar runs, so anything that changes
the line count between the file on disk and the text handed to Lark makes every
reported position downstream of it wrong.
"""

from pathlib import Path

from cobble.interpreter.project.cobol_imports import extract_cobol_imports
from cobble.interpreter.project.import_types import ImportKind


def test_a_copy_reports_the_line_it_is_on() -> None:
    src = b"       PROGRAM-ID. FOO.\n       WORKING-STORAGE SECTION.\n       COPY CUSTREC.\n"
    (ref,) = extract_cobol_imports(src, Path("FOO.cbl"))
    assert ref.module_path == "CUSTREC"
    assert ref.line == 3


def test_a_copy_after_comment_lines_reports_its_true_source_line() -> None:
    """Comment lines used to be *deleted* before tokenisation, which shifted every
    position after them up by the number of comments removed."""
    src = (
        b"       PROGRAM-ID. FOO.\n"
        b"      * a box comment\n"
        b"      * another one\n"
        b"      / and a page eject\n"
        b"       COPY CUSTREC.\n"
    )
    (ref,) = extract_cobol_imports(src, Path("FOO.cbl"))
    assert ref.line == 5


def test_a_copy_after_a_free_format_comment_reports_its_true_source_line() -> None:
    src = b"       PROGRAM-ID. FOO.\n    *> free-format comment\n       COPY CUSTREC.\n"
    (ref,) = extract_cobol_imports(src, Path("FOO.cbl"))
    assert ref.line == 3


def test_a_call_reports_the_line_it_is_on() -> None:
    src = b"       PROGRAM-ID. FOO.\n\n       CALL 'SUBPROG'.\n"
    (ref,) = extract_cobol_imports(src, Path("FOO.cbl"))
    assert ref.kind == ImportKind.REQUIRE
    assert ref.line == 3


def test_the_same_copybook_copied_twice_reports_both_lines() -> None:
    """The diagnostic groups by copybook name, so two COPYs of one name in one
    program must stay two entries with distinct lines, not collapse to one."""
    src = b"       COPY CUSTREC.\n       DISPLAY 'X'.\n       COPY CUSTREC.\n"
    refs = extract_cobol_imports(src, Path("FOO.cbl"))
    assert [r.line for r in refs] == [1, 3]
