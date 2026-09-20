"""Unit tests for CICS text pre-pass."""

from tests.covers import covers, NotLanguageFeature
from cics.preprocessor import (
    inject_dfheiblk,
    apply_cics_prepass,
    _DFHRESP_TABLE,
    _DFHRESP_UNKNOWN,
)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_inject_dfheiblk_inserts_after_ws_section():
    source = "       WORKING-STORAGE SECTION.\n" "       01 WS-DUMMY PIC X.\n"
    result = inject_dfheiblk(source)
    lines = result.splitlines()
    assert lines[0] == "       WORKING-STORAGE SECTION."
    assert "COPY DFHEIBLK." in lines[1]
    assert "WS-DUMMY" in lines[2]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_inject_dfheiblk_no_change_if_no_ws_section():
    source = "       PROCEDURE DIVISION.\n       STOP RUN.\n"
    assert inject_dfheiblk(source) == source


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_inject_dfheiblk_case_insensitive():
    source = "       working-storage section.\n       01 X PIC X.\n"
    result = inject_dfheiblk(source)
    assert "COPY DFHEIBLK." in result


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_apply_cics_prepass_injects_both_copybooks_and_preserves_dfhresp():
    """apply_cics_prepass injects DFHEIBLK and DFHHANDLE but leaves DFHRESP
    literals intact.

    DFHRESP(X) is now lowered structurally by the ProLeap bridge (red-dragon-kieo);
    the pre-pass no longer performs text substitution.
    """
    source = (
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-X PIC X.\n"
        "       PROCEDURE DIVISION.\n"
        "           IF X = DFHRESP(NORMAL)\n"
        "               STOP RUN.\n"
    )
    result = apply_cics_prepass(source)
    assert "COPY DFHEIBLK." in result
    assert "COPY DFHHANDLE." in result
    assert "DFHRESP(NORMAL)" in result


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_inject_dfheiblk_injects_only_once():
    """Malformed source with two WS sections gets exactly one injection."""
    source = (
        "       WORKING-STORAGE SECTION.\n"
        "       01 X PIC X.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 Y PIC X.\n"
    )
    result = inject_dfheiblk(source)
    assert result.count("COPY DFHEIBLK.") == 1


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dfhresp_table_values_are_unique():
    """No two conditions may share a code, else they'd compare-equal."""
    assert len(set(_DFHRESP_TABLE.values())) == len(_DFHRESP_TABLE)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dfhresp_unknown_sentinel_not_in_table():
    """The sentinel value must not collide with any real DFHRESP code."""
    assert _DFHRESP_UNKNOWN not in _DFHRESP_TABLE.values()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_working_storage_is_found_in_sequence_numbered_source():
    """003700 WORKING-STORAGE SECTION. — the sequence number is not a token."""
    source = (
        "003600 DATA DIVISION.                                                   00360000\n"
        "003700 WORKING-STORAGE SECTION.                                         00370000\n"
        "003800 01 WS-FOO PIC X.                                                 00380000\n"
    )

    result = apply_cics_prepass(source)

    assert "COPY DFHEIBLK." in result


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_working_storage_is_still_found_without_sequence_numbers():
    """Blank sequence field (Area A at col 8), not a column-2 fixture — that
    is not valid fixed-format COBOL and the bridge is hard-wired to FIXED."""
    source = (
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-FOO PIC X.\n"
    )

    assert "COPY DFHEIBLK." in apply_cics_prepass(source)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_injection_does_not_disturb_the_identification_area():
    """Regression guard for both the detection fix and the injection
    mechanism: the header must actually be found (fails pre-fix, since
    nothing was injected into sequence-numbered source), and the original
    line's identification area (cols 73-80) must survive untouched."""
    source = "003700 WORKING-STORAGE SECTION.                                         00370000\n"

    result = apply_cics_prepass(source)

    assert "COPY DFHEIBLK." in result
    ws_line = next(l for l in result.splitlines() if "WORKING-STORAGE" in l)
    assert ws_line[72:80] == "00370000"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_comment_line_mentioning_working_storage_is_not_the_header():
    """003650* WORKING-STORAGE SECTION. — a comment, not the real header."""
    source = (
        "003650*    WORKING-STORAGE SECTION. (see below)                        00365000\n"
        "003700 WORKING-STORAGE SECTION.                                         00370000\n"
        "003800 01 WS-FOO PIC X.                                                 00380000\n"
    )

    result = apply_cics_prepass(source)

    lines = result.splitlines()
    comment_index = next(i for i, l in enumerate(lines) if "003650" in l)
    assert "COPY DFHEIBLK." not in lines[comment_index + 1]
    real_header_index = next(
        i for i, l in enumerate(lines) if l.strip().startswith("003700")
    )
    assert "COPY DFHHANDLE." in lines[real_header_index + 1]
    assert "COPY DFHEIBLK." in result


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_short_line_code_area_does_not_raise():
    """A line with no code area at all (shorter than col 8, including the
    boundary case of exactly 7 characters) yields an empty code area rather
    than raising or fabricating one."""
    from cics.preprocessor import _code_area, _is_ws_section

    assert _code_area("AB") == ""
    assert _code_area("1234567") == ""
    assert _is_ws_section("AB") is False
    assert _is_ws_section("1234567") is False
