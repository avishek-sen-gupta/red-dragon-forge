"""The COPY/CALL scanner's source positions.

A COPY's line number is what makes a missing copybook actionable: 315 names
missing across 1766 programs is a number, ``member X line 412`` is somewhere to
look. The scanner is the one place that knows it, and it has to be exact —
comment lines are stripped before the grammar runs, so anything that changes
the line count between the file on disk and the text handed to Lark makes every
reported position downstream of it wrong.
"""

from pathlib import Path

from cobol_asg.cobol_imports import extract_cobol_imports
from cobol_asg.import_types import ImportKind


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


# ── fixed-format continuation ────────────────────────────────────
#
# A non-numeric literal too long for area B is split at column 72 and resumed on
# the next line, which carries '-' in column 7 and re-opens with a quote. Reading
# such a member a line at a time is not merely imprecise, it is four distinct
# defects: a split COPY name reports a truncated name that resolves to nothing, a
# split CALL literal is missed outright, and text inside the open literal gets
# scanned as code, which invents COPY/CALL statements that are prose.
#
# The indicator lives at column 7, so folding is inherently fixed-format. That is
# what the corpus is: no caller sets the bridge's source format flag, so it always
# takes its FIXED default, and source_text decodes fixed-format members.


def test_a_copy_name_split_across_a_continuation_reports_the_whole_name() -> None:
    """Worse than a miss: the unfolded read yields LONGCOPYBOOKNAM, a name no
    copybook has, which the diagnostic then reports as unresolvable."""
    src = b"       COPY LONGCOPYBOOKNAM\n      -    E.\n"
    (ref,) = extract_cobol_imports(src, Path("FOO.cbl"))
    assert ref.module_path == "LONGCOPYBOOKNAME"


def test_a_call_literal_split_across_a_continuation_is_found() -> None:
    """CALL_STMT needs a complete quoted literal, so a split one matches nothing
    and the call edge simply disappears."""
    src = b"       CALL 'SUBPRO\n      -    'GRAM' USING WS-A.\n"
    (ref,) = extract_cobol_imports(src, Path("FOO.cbl"))
    assert ref.kind == ImportKind.REQUIRE
    assert ref.module_path == "SUBPROGRAM"


def test_a_copy_keyword_inside_a_continued_literal_is_not_reported() -> None:
    """Prose in a message literal is not a copy statement. Unfolded, the open
    quote cannot be paired, so the literal's words are tokenised as code."""
    src = b"       MOVE 'PLS COPY MEMBER1 NO\n      -    'W' TO WS-MSG.\n"
    assert extract_cobol_imports(src, Path("FOO.cbl")) == []


def test_a_copy_keyword_split_inside_a_continued_literal_is_not_reported() -> None:
    """The same defect with the literal's own text split, which unfolded invents
    a COPY of MEMB -- a name assembled out of half a word."""
    src = b"       MOVE 'ASK THEM TO COPY MEMB\n      -    'ER1 TODAY' TO WS-MSG.\n"
    assert extract_cobol_imports(src, Path("FOO.cbl")) == []


def test_a_doubled_quote_before_a_continuation_does_not_close_the_literal() -> None:
    """'' inside a literal is an escaped quote, not its terminator. Treating it
    as the end makes the following line look like code rather than a resume."""
    src = (
        b"       MOVE 'IT''S A LONG\n"
        b"      -    ' MESSAGE' TO WS-MSG.\n"
        b"       COPY CUSTREC.\n"
    )
    (ref,) = extract_cobol_imports(src, Path("FOO.cbl"))
    assert ref.module_path == "CUSTREC"
    assert ref.line == 3


def test_a_comment_line_may_sit_between_a_line_and_its_continuation() -> None:
    """A comment line is legal anywhere, including inside a continued statement.
    Dropping it must not make the continuation attach to the comment instead of
    to the line it continues."""
    src = (
        b"       MOVE 'ABC\n"
        b"      * a box comment\n"
        b"      -    'DEF' TO WS-MSG.\n"
        b"       COPY CUSTREC.\n"
    )
    (ref,) = extract_cobol_imports(src, Path("FOO.cbl"))
    assert ref.module_path == "CUSTREC"
    assert ref.line == 4


def test_a_word_continuation_joins_with_no_intervening_space() -> None:
    """Fixed-format continuation splices the first nonblank of area B directly
    onto the last nonblank of the continued line -- a space would be a different
    program, and is why continuation is only ever used mid-token."""
    src = b"       COPY CUST\n      -    REC.\n"
    (ref,) = extract_cobol_imports(src, Path("FOO.cbl"))
    assert ref.module_path == "CUSTREC"


def test_a_copy_after_a_continuation_reports_its_true_source_line() -> None:
    """Folding joins lines, so a token's position in the folded text is no longer
    its position in the file. Without a map back, every ref after the first
    continuation points at the wrong line."""
    src = (
        b"       MOVE 'ABCDEFGHIJ\n"
        b"      -    'KLM' TO WS-MSG.\n"
        b"       COPY CUSTREC.\n"
    )
    (ref,) = extract_cobol_imports(src, Path("FOO.cbl"))
    assert ref.line == 3


def test_text_in_the_identification_area_is_not_scanned_as_code() -> None:
    """Columns 73-80 are the identification area, not program text. A member
    stamped there with something COPY-shaped must not become an edge."""
    src = b"       DISPLAY 'X'.".ljust(72) + b"COPY XX\n"
    assert extract_cobol_imports(src, Path("FOO.cbl")) == []


# ── malformed source: tolerance, not correctness ──────────────────


def test_an_unterminated_literal_does_not_hide_a_later_copy() -> None:
    """The 328-member failure. STRING matched newlines, so an unterminated quote
    paired with the next line's quote, the mispairing cascaded, and eventually
    nothing matched -- taking every COPY in the rest of the file with it.

    This source is malformed COBOL (a continuation that resumes no literal), so
    folding cannot rescue it. What matters is that it degrades to noise instead
    of raising, because a member cobble cannot read is a member build_graph drops
    from the graph entirely.
    """
    src = b"       MOVE 'UNTERMINATED\n       DISPLAY 'X'.\n       COPY CUSTREC.\n"
    refs = extract_cobol_imports(src, Path("FOO.cbl"))
    assert [r.module_path for r in refs] == ["CUSTREC"]
