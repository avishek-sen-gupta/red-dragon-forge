"""Unit tests for squall.fixed_format — the positional fixed-format line model.

Policy for the real-corpus round-trip test at the bottom: run everywhere (CI
and local) when the CardDemo submodule is available, fail with setup guidance
when it is not. No silent skips — a wrong or missing corpus must never hide a
regression in the zone model, which is the strongest evidence this module is
correct. Mirrors cicada/tests/integration/cics/conftest.py's policy and
resolution order.
"""

from pathlib import Path

import os
import pytest

from squall.fixed_format import (
    CodeAreaOverflow,
    InvalidSpan,
    parse_line,
    render,
    replace_span,
    with_code,
)

_NUMBERED = (
    "028600      EXEC SQL INCLUDE DCLTRTYP END-EXEC                          02860000"
)
_PLAIN = "           MOVE A TO B."


def test_parses_the_four_zones():
    line = parse_line(_NUMBERED)

    assert line.sequence == "028600"
    assert line.indicator == " "
    assert line.code.strip() == "EXEC SQL INCLUDE DCLTRTYP END-EXEC"
    assert line.identification == "02860000"


def test_render_round_trips_exactly():
    assert render(parse_line(_NUMBERED)) == _NUMBERED
    assert render(parse_line(_PLAIN)) == _PLAIN


def test_render_round_trips_lines_shorter_than_seven_columns():
    for raw in ("", "A", "ABCDEF", "ABCDEFG"):
        assert render(parse_line(raw)) == raw


def test_render_round_trips_a_line_exactly_eighty_columns():
    raw = "A" * 80
    assert render(parse_line(raw)) == raw


def test_render_round_trips_a_line_shorter_than_seventy_three_columns():
    raw = "028600      EXEC SQL"
    assert render(parse_line(raw)) == raw


def test_render_strips_trailing_spaces_when_there_is_no_identification_area():
    """Deliberate exception, not a round-trip gap: a line under 73 columns has
    no identification area to preserve, and COBOL itself ignores trailing
    blanks in Area B, so render right-strips rather than reproducing them
    byte-for-byte. The brief prescribes this; pinned here so it reads as
    intentional rather than an oversight."""
    assert render(parse_line("MOVE A TO B.  ")) == "MOVE A TO B."


def test_a_line_with_no_identification_area_does_not_gain_one():
    """Most CardDemo programs have no sequence area at all. Rewriting must not
    manufacture zones by padding every line out to 80 columns.

    ``with_code`` takes the code area verbatim, with no auto-indentation —
    placing "MOVE C TO D." at column 8 (index 7) yields 7 leading spaces, not
    11: the brief's original assertion of 11 spaces assumed an
    auto-indenting rewriter, which this module deliberately is not (guessing
    Area A vs. Area B is what produced this bug class)."""
    line = parse_line(_PLAIN)

    assert line.identification == ""
    assert render(with_code(line, "MOVE C TO D.")) == "       MOVE C TO D."


def test_shortening_a_rewrite_keeps_the_identification_area_at_column_73():
    """The whole point. COPY DCLTRTYP. is 20 chars shorter than what it
    replaces; 02860000 must not move."""
    rewritten = render(with_code(parse_line(_NUMBERED), "     COPY DCLTRTYP."))

    assert rewritten[72:80] == "02860000"
    assert rewritten[6] == " "
    assert "COPY DCLTRTYP." in rewritten[7:72]


def test_code_at_exactly_the_code_area_width_does_not_overflow():
    line = with_code(parse_line(_NUMBERED), "X" * 65)

    assert len(line.code) == 65


def test_code_one_column_past_the_code_area_width_overflows():
    with pytest.raises(CodeAreaOverflow):
        with_code(parse_line(_NUMBERED), "X" * 66)


def test_code_that_overflows_the_area_raises_rather_than_truncating():
    with pytest.raises(CodeAreaOverflow) as excinfo:
        with_code(parse_line(_NUMBERED), "X" * 70)

    assert str(excinfo.value).find("70") != -1


def test_replace_span_empties_later_lines_but_keeps_their_own_fields():
    raw = [
        "028600      EXEC SQL                                                    02860000",
        "028700      INCLUDE SQLCA                                               02870000",
        "028800      END-EXEC                                                    02880000",
    ]
    lines = [parse_line(r) for r in raw]

    out = replace_span(lines, 0, 2, "     COPY SQLCA.")

    assert len(out) == 3
    assert render(out[0])[72:80] == "02860000"
    assert render(out[1])[72:80] == "02870000"
    assert render(out[2])[72:80] == "02880000"
    assert "COPY SQLCA." in render(out[0])
    assert render(out[1])[7:72].strip() == ""
    assert render(out[2])[7:72].strip() == ""


def test_replace_span_leaves_lines_outside_the_span_untouched():
    raw = [
        "028500      DISPLAY 'BEFORE'                                            02850000",
        "028600      EXEC SQL                                                    02860000",
        "028700      END-EXEC                                                    02870000",
        "028800      DISPLAY 'AFTER'                                             02880000",
    ]
    lines = [parse_line(r) for r in raw]

    out = replace_span(lines, 1, 2, "     COPY SQLCA.")

    assert render(out[0]) == raw[0]
    assert render(out[3]) == raw[3]


def test_replace_span_accepts_a_single_line_span():
    lines = [parse_line(_NUMBERED)]

    out = replace_span(lines, 0, 0, "     COPY DCLTRTYP.")

    assert len(out) == 1
    assert render(out[0])[72:80] == "02860000"


def test_replace_span_rejects_end_before_start():
    lines = [parse_line(_NUMBERED)] * 4

    with pytest.raises(InvalidSpan):
        replace_span(lines, 2, 0, "     COPY DCLTRTYP.")


def test_replace_span_rejects_negative_start():
    lines = [parse_line(_NUMBERED)] * 4

    with pytest.raises(InvalidSpan):
        replace_span(lines, -1, 2, "     COPY DCLTRTYP.")


def test_replace_span_rejects_end_past_the_last_index():
    lines = [parse_line(_NUMBERED)] * 4

    with pytest.raises(InvalidSpan):
        replace_span(lines, 0, 4, "     COPY DCLTRTYP.")


def test_rewriting_never_leaves_a_stray_token_in_the_code_area():
    """A bare sequence-shaped token in Area B makes ANTLR's error recovery eat
    the FOLLOWING 01 group, silently and with exit 0. This is what corrupted
    CARDDEMO-COMMAREA. No rewrite may produce it."""
    line = parse_line(_NUMBERED)

    rewritten = render(with_code(line, "     COPY DCLTRTYP."))

    assert rewritten[7:72].find("02860000") == -1


# ── Real-corpus round-trip ───────────────────────────────────────────────────
# Resolution order for CARDDEMO_HOME, matching cicada's e2e gate:
#   1. CARDDEMO_HOME env var (explicit override)
#   2. vendor/carddemo/app submodule (auto-detected from the monorepo root)
# A wrong override or a missing submodule fails the test outright — it never
# degrades to a skip.

_MONOREPO_ROOT = Path(__file__).resolve().parents[3]
_SUBMODULE_CARDDEMO_APP = _MONOREPO_ROOT / "vendor" / "carddemo" / "app"
_CARDDEMO_HOME = Path(os.environ.get("CARDDEMO_HOME") or _SUBMODULE_CARDDEMO_APP)
_CARDDEMO_CBL_PATHS = tuple(
    _CARDDEMO_HOME / "app-transaction-type-db2" / "cbl" / name
    for name in ("COTRTUPC.cbl", "COTRTLIC.cbl")
)


def test_round_trips_every_line_of_a_real_carddemo_program():
    missing = [p for p in _CARDDEMO_CBL_PATHS if not p.is_file()]
    if missing:
        pytest.fail(
            "CardDemo corpus not found for the fixed_format round-trip check "
            f"(resolved CARDDEMO_HOME={_CARDDEMO_HOME}); missing: "
            f"{', '.join(str(p) for p in missing)}. Run "
            "`git submodule update --init vendor/carddemo`, or set CARDDEMO_HOME.",
            pytrace=False,
        )

    for path in _CARDDEMO_CBL_PATHS:
        for raw in path.read_text(encoding="utf-8").splitlines():
            assert render(parse_line(raw)) == raw
